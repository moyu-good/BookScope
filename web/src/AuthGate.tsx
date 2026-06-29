// 托管版登录 / 注册界面(1.6.2 FE)。
//
// 两块:
//   - AuthModal:登录 / 注册弹窗。邮箱 / 密码;切换登录注册;错误回显人话。
//     只在 hosted 模式、且没登录时挂出来。
//   - AccountStrip:左栏底部的"当前账号 + 退出"一行。登录后显示邮箱;退出=前端清令牌。
//
// 样式沿用全站 app-shell 那套 CSS 变量(--color-ink / --color-seal / --color-paper-raised
// / --color-rule / --font-display / --shadow-soft),不引第三方 UI。汉风文案、无 emoji、无
// 破折号补语。本地克隆版根本不渲染这两块(App 里 hosted 才挂)。

import { useState } from "react";
import type { FormEvent } from "react";
import type { AuthUser } from "./authClient";
import { authErrorText, login, register, saveAuthToken } from "./authClient";

type AuthTab = "login" | "register";

export function AuthModal({
  onAuthed,
}: {
  /** 登录 / 注册成功:把用户传上去,App 存令牌已在内部做、这里只回传 user。 */
  onAuthed: (user: AuthUser) => void;
}) {
  const [tab, setTab] = useState<AuthTab>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState("");

  const canSubmit =
    email.trim().length >= 3 &&
    password.length >= (tab === "register" ? 8 : 1) &&
    !busy;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setErrMsg("");
    try {
      const resp =
        tab === "register"
          ? await register({
              email: email.trim(),
              password,
            })
          : await login({ email: email.trim(), password });
      saveAuthToken(resp.token);
      onAuthed(resp.user);
    } catch (err) {
      setErrMsg(authErrorText(err));
    } finally {
      setBusy(false);
    }
  }

  function switchTab(next: AuthTab) {
    setTab(next);
    setErrMsg("");
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{
        background: "color-mix(in oklch, var(--color-ink) 38%, transparent)",
      }}
    >
      <div
        className="reveal w-full max-w-sm rounded-lg border border-[var(--color-rule)] p-6"
        style={{
          background: "var(--color-paper-raised)",
          boxShadow: "var(--shadow-soft)",
        }}
        role="dialog"
        aria-modal="true"
        aria-label={tab === "register" ? "注册账号" : "登录账号"}
      >
        {/* 朱印 + 标题 */}
        <div className="flex flex-col items-center gap-2 mb-5">
          <span
            className="seal-stamp inline-flex items-center justify-center w-11 h-11 rounded-[5px] text-[var(--color-paper)] select-none"
            style={{
              background: "var(--color-seal)",
              fontFamily: "var(--font-display)",
              fontSize: "1.55rem",
              boxShadow: "var(--shadow-soft)",
              transform: "rotate(-2deg)",
            }}
            aria-hidden="true"
          >
            鑒
          </span>
          <h2
            className="text-lg text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}
          >
            {tab === "register" ? "注册书鉴账号" : "登录书鉴"}
          </h2>
          <p className="text-xs text-[var(--color-ink-muted)] text-center leading-relaxed">
            托管版用账号把你传的书存住,换设备回来接着读。你的 LLM key 只在浏览器,账号碰不到。
          </p>
        </div>

        {/* 登录 / 注册切换 */}
        <div
          className="flex rounded-md p-0.5 mb-4"
          style={{ background: "var(--color-paper)" }}
        >
          {(["login", "register"] as AuthTab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => switchTab(t)}
              className="flex-1 py-1.5 text-sm rounded transition-colors"
              style={
                tab === t
                  ? {
                      background: "var(--color-seal)",
                      color: "#fff",
                      fontFamily: "var(--font-display)",
                    }
                  : { color: "var(--color-ink-muted)" }
              }
            >
              {t === "login" ? "登录" : "注册"}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <Field
            id="auth-email"
            label="邮箱"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="you@example.com"
            autoComplete="username"
          />
          <Field
            id="auth-password"
            label="密码"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder={tab === "register" ? "至少 8 位" : "你的密码"}
            autoComplete={tab === "register" ? "new-password" : "current-password"}
          />

          {errMsg && (
            <p
              className="text-xs px-3 py-2 rounded"
              style={{
                background: "var(--color-seal-soft)",
                color: "var(--color-seal)",
              }}
            >
              {errMsg}
            </p>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="mt-1 inline-flex items-center justify-center gap-2 bg-[var(--color-seal)] text-white px-5 py-2.5 rounded hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-all"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {busy ? (
              <>
                <span className="animate-pulse">●</span>
                {tab === "register" ? "注册中" : "登录中"}
              </>
            ) : tab === "register" ? (
              "注册并登录"
            ) : (
              "登录"
            )}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-[var(--color-ink-muted)] leading-relaxed">
          {tab === "login" ? "还没有账号?" : "已经有账号了?"}
          <button
            type="button"
            onClick={() => switchTab(tab === "login" ? "register" : "login")}
            className="ml-1 text-[var(--color-seal)] hover:underline"
          >
            {tab === "login" ? "去注册" : "去登录"}
          </button>
        </p>
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  type,
  value,
  onChange,
  placeholder,
  autoComplete,
}: {
  id: string;
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label
        htmlFor={id}
        className="text-sm text-[var(--color-ink-muted)]"
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className="w-full rounded border border-[var(--color-rule)] px-3 py-2 text-sm text-[var(--color-ink)] focus:border-[var(--color-seal)] focus:outline-none transition-colors"
        style={{ background: "var(--color-paper)" }}
      />
    </div>
  );
}

/** 左栏底部账号条:显示当前邮箱 + 退出。只在 hosted 且已登录时挂。 */
export function AccountStrip({
  user,
  onLogout,
}: {
  user: AuthUser;
  onLogout: () => void;
}) {
  return (
    <div
      className="px-3 py-3 flex items-center justify-between gap-2"
      style={{ borderTop: "1px solid var(--color-rule)" }}
    >
      <div className="min-w-0">
        <div className="text-[10.5px] tracking-wider text-[var(--color-ink-muted)]">
          当前账号
        </div>
        <div
          className="text-[13px] text-[var(--color-ink)] truncate"
          title={user.email}
          style={{ fontFamily: "var(--font-display)" }}
        >
          {user.email}
        </div>
      </div>
      <button
        type="button"
        onClick={onLogout}
        className="shrink-0 text-xs px-2.5 py-1.5 rounded border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] transition-colors"
      >
        退出
      </button>
    </div>
  );
}
