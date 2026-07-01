// 托管版账号客户端（1.6.2 FE）。
//
// 一条链:探测部署形态 → 存令牌 → 登录/注册/验明身份/退出 → 给 API 请求挂 Bearer。
//
// 设计要点(对齐 WP-1.6.2-account-backend §4.5 红线 + CLAUDE.md local 零变化):
//   - 令牌存 localStorage `bookscope_auth_token`,跟 BYOK key(`bookscope_llm_config_v1`)
//     **分开存**。账号令牌只装 user_id,不含任何 LLM key;key 永远只在浏览器、按请求传。
//   - 令牌注入挂在**一个集中处**:包装全局 window.fetch。只给同源 `/api/*` 请求、且确有
//     令牌时加 `Authorization: Bearer`;没令牌就一个头都不加,所有现有端点照旧匿名走。
//     本地克隆版(deployment_mode=local)永远不会有令牌 → 这层包装是纯透传 → 行为逐字节不变。
//   - 探测:启动 fetch `GET /api/health` 读 deployment_mode;local 就当账号功能不存在。

const AUTH_TOKEN_KEY = "bookscope_auth_token";

export type DeploymentMode = "local" | "hosted";

export interface AuthUser {
  id: string;
  email: string;
  phone: string | null;
  /** 邮箱是否已验证（后端 UserPublic.email_verified）。「我的案头」据此显验证态。 */
  email_verified: boolean;
  created_at: string;
}

// 与 bookscope.api.schemas.AuthResponse 对齐。
interface AuthResponse {
  token: string;
  user: AuthUser;
}

// 与 bookscope.api.schemas.HealthResponse 对齐(只取要用的字段)。
interface HealthResponse {
  deployment_mode?: DeploymentMode;
}

/** 账号 API 抛出的错误:带后端 HTTP 状态码,供 UI 翻成人话(409/401/422)。 */
export class AuthApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
  }
}

// ---------------------------------------------------------------------------
// 令牌存取(localStorage,跟 BYOK key 分开存)
// ---------------------------------------------------------------------------

export function loadAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const t = window.localStorage.getItem(AUTH_TOKEN_KEY);
    return t && t.length > 0 ? t : null;
  } catch {
    return null;
  }
}

export function saveAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  } catch {
    // 隐私模式 / 配额满——失败默默忽略,不阻断主流程
  }
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  } catch {
    // 同上
  }
}

// ---------------------------------------------------------------------------
// 令牌注入:包装全局 fetch(唯一集中处)
// ---------------------------------------------------------------------------

let installed = false;

/**
 * 给全局 fetch 装一层令牌注入。装一次即可(重复调用无副作用)。
 *
 * 只在两个条件**同时**满足时加 `Authorization: Bearer`:
 *   1. 请求是同源 `/api/...`(不给跨域请求、不给静态资源加头);
 *   2. 本地存了令牌(loadAuthToken() 非空)。
 *
 * 调用方已显式带了 Authorization 头的,尊重原值不覆盖。
 *
 * local 模式永远没令牌 → 这里永远走 else 透传 → 现有所有请求逐字节不变。
 */
export function installAuthFetch(): void {
  if (installed) return;
  if (typeof window === "undefined" || typeof window.fetch !== "function") return;
  installed = true;

  const original = window.fetch.bind(window);

  window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const token = loadAuthToken();
    if (!token || !isSameOriginApi(input)) {
      return original(input, init);
    }

    // 已带 Authorization 的(比如将来某处自定义)不覆盖。
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    if (headers.has("Authorization")) {
      return original(input, init);
    }
    headers.set("Authorization", `Bearer ${token}`);
    return original(input, { ...init, headers });
  };
}

/** 判一个 fetch 目标是不是同源的 `/api/...`。只有这类请求才挂令牌。 */
function isSameOriginApi(input: RequestInfo | URL): boolean {
  let url: string;
  if (typeof input === "string") url = input;
  else if (input instanceof URL) url = input.toString();
  else if (input instanceof Request) url = input.url;
  else return false;

  // 相对路径(现有调用全是 `/api/...` 这种)直接看前缀。
  if (url.startsWith("/api/")) return true;
  // 绝对 URL:同源且路径打头 /api/ 才算。
  try {
    const u = new URL(url, window.location.href);
    return u.origin === window.location.origin && u.pathname.startsWith("/api/");
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// 探测部署形态
// ---------------------------------------------------------------------------

/**
 * 探测部署形态。fetch `GET /api/health` 读 deployment_mode。
 * 探不通 / 字段缺一律当 local(保守:出问题就当账号功能不存在,绝不误显登录面)。
 */
export async function probeDeployment(): Promise<DeploymentMode> {
  try {
    const resp = await fetch("/api/health");
    if (!resp.ok) return "local";
    const data = (await resp.json()) as HealthResponse;
    return data.deployment_mode === "hosted" ? "hosted" : "local";
  } catch {
    return "local";
  }
}

// ---------------------------------------------------------------------------
// 账号 API
// ---------------------------------------------------------------------------

async function authErr(resp: Response): Promise<AuthApiError> {
  let detail = "";
  try {
    const body = await resp.json();
    const d = body?.detail;
    if (typeof d === "string") detail = d;
    else if (Array.isArray(d) && d.length > 0 && typeof d[0]?.msg === "string") {
      // FastAPI 422 校验错误形态:detail 是 [{msg, loc, ...}]
      detail = d[0].msg;
    } else if (d) detail = JSON.stringify(d);
  } catch {
    // body 不是 JSON——用状态文本兜底
  }
  return new AuthApiError(resp.status, detail || resp.statusText);
}

/** 注册:邮箱 + 密码(+ 可选手机)。成功返令牌 + 用户;邮箱占用 409。 */
export async function register(args: {
  email: string;
  password: string;
  phone?: string;
}): Promise<AuthResponse> {
  const body: Record<string, unknown> = {
    email: args.email,
    password: args.password,
  };
  if (args.phone && args.phone.trim()) body.phone = args.phone.trim();
  const resp = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw await authErr(resp);
  return (await resp.json()) as AuthResponse;
}

/** 登录:邮箱 + 密码。不对 401。 */
export async function login(args: {
  email: string;
  password: string;
}): Promise<AuthResponse> {
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: args.email, password: args.password }),
  });
  if (!resp.ok) throw await authErr(resp);
  return (await resp.json()) as AuthResponse;
}

/**
 * 带令牌问"我是谁"。令牌由 installAuthFetch 自动挂上。
 * 没登录 / 令牌坏 → 401 → 返 null(调用方据此清掉过期令牌)。
 */
export async function fetchMe(): Promise<AuthUser | null> {
  try {
    const resp = await fetch("/api/auth/me");
    if (resp.status === 401) return null;
    if (!resp.ok) return null;
    return (await resp.json()) as AuthUser;
  } catch {
    return null;
  }
}

/** 退出:纯前端清令牌(令牌是签名时限的,前端丢弃即失效访问)。 */
export function logout(): void {
  clearAuthToken();
}

/** 把后端账号错误翻成给人看的中文。 */
export function authErrorText(err: unknown): string {
  if (err instanceof AuthApiError) {
    if (err.status === 409) return "这个邮箱已经注册过了,直接登录吧。";
    if (err.status === 401) return "邮箱或密码不对,再核对一下。";
    if (err.status === 422) return err.message || "邮箱或密码格式不对。";
    return err.message || "出了点问题,稍后再试。";
  }
  return "网络不通,检查一下连接再试。";
}
