# BookScope 部署记录

> 公网 BYOK 网站上线实录。代码是事实源，这份文档记的是"实际怎么部署的 + 踩了什么坑 + 线上现状"，给未来的自己和另一台机器看。
> 首次上线：2026-06-28。线上地址：`https://bookscope.top`

## 线上架构

```
访客 ──HTTPS──> Cloudflare 边缘 ──命名隧道──> 腾讯云服务器 :8000（仅本机监听）
                                              │
                                    Docker 容器 (python:3.12-slim)
                                    ├─ uvicorn 单 worker (BookSessionStore 进程级单例)
                                    ├─ FastAPI /api/*  后端
                                    ├─ StaticFiles /  前端 dist (同源,免 CORS)
                                    └─ 持久卷 /app/data  (sessions + 缓存 SQLite)
```

- **服务器**：腾讯云 2核4G / 70GB SSD / 6Mbps 带宽，Debian，到期 2027-03-31。选国内 = DeepSeek 国内直连最顺。
- **域名**：`bookscope.top`（腾讯云买，首年 ~¥10）。Cloudflare Registrar 不卖 `.top`，所以只在腾讯云买、DNS 托管到 Cloudflare。
- **HTTPS / 免备案**：Cloudflare Tunnel 命名隧道。服务器不开入站端口、域名解析到 CF 而非国内 IP，腾讯云备案拦截不触发。国内访客走 CF 海外边缘多 100-300ms，对"传书等几分钟"的应用可接受。
- **单 worker 硬约束**：`BookSessionStore` 是进程级单例（`bookscope/api/book_sessions.py`），多 worker 各持一份内存会 session 错位。扩容才需加实例 + 共享存储（`supabase_repository.py` 已备）。

## 部署踩坑三连（都在 main 上修了）

首次部署卡了一小时，三个坑连着来，全部是"国内服务器 + slim 镜像"环境问题，非代码逻辑 bug：

1. **hatchling 读 readme**（commit `a440069`）
   `pyproject.toml` 声明 `readme = "README.md"`，但 Dockerfile 在 `pip install` 前只 COPY 了 `pyproject.toml` 和 `bookscope/__init__.py`，hatchling 构建元数据时找不到 README.md 崩掉。修：`pip install` 前加 `COPY README.md ./`。`.dockerignore` 虽 `!README.md` 白名单了，但 Dockerfile 没 COPY 等于没用——**两处都得对**。

2. **NLTK 语料默认源国内拉 26 分钟**（commit `b773f06`）
   `textblob.download_corpora` 走 NLTK 默认源 `raw.githubusercontent.com`，腾讯云拉 20+ 分钟。修：Dockerfile 里改成手动 `curl` ghproxy 镜像下 nrclex/textblob 实际用到的最小语料集（punkt/punkt_tab/perceptron_tagger/wordnet/brown），多镜像 fallback（gh-proxy.com → ghproxy.net → 原始源）。不装 conll2000/movie_reviews——nrclex 用不到。

3. **slim 镜像无 unzip**（commit `e776066`）
   坑 2 的解压用 `unzip`，但 python:3.12-slim 没装 unzip，curl 下下来解不开。修：改用 `python -c "import zipfile; zipfile.ZipFile(...).extractall(...)"`，不增加系统依赖。

> 教训：国内服务器部署，**所有从 GitHub/raw.githubusercontent 拉东西的环节都要换镜像源**——pip 换清华、npm 换淘宝、apt 换清华、NLTK 换 ghproxy。Dockerfile 里已全部换好。

## Cloudflare Tunnel 配置（命名隧道）

临时隧道（`*.trycloudflare.com`）只用于首次验证，重启会变 URL，不能长期用。正式上线切命名隧道：

1. **域名托管到 CF**：CF Add Site → 输入 `bookscope.top` → Free 计划 → CF 给两条 NS（本例 `kelly.ns.cloudflare.com` / `khalid.ns.cloudflare.com`）→ 回腾讯云域名管理把默认 dnspod NS 改成 CF 的两条 → 等 10 分钟~几小时生效（CF 页面 Pending→Active）。DNSSEC 若开要关。
2. **建隧道**：CF Zero Trust（`one.dash.cloudflare.com`，Free 计划够用、不自动扣费、50 用户上限但 BYOK 公开站不碰用户系统）→ Networks → Tunnels → Create → Cloudflared → 命名 `bookscope` → 拿 TOKEN。
3. **服务器填 TOKEN**：`~/BookScope/.env` 里设 `TUNNEL_TOKEN=<TOKEN>` 和 `TUNNEL_CMD=tunnel run --token <TOKEN>`，`docker compose up -d` 重启 tunnel 容器。
4. **配路由**：隧道详情页 → "已发布应用程序路由 / Published application routes"（新版改名，不叫 Public Hostname）→ 添加两条：`bookscope.top → http://api:8000`、`www.bookscope.top → http://api:8000`。
5. 验证：`curl -fsS https://bookscope.top/api/health` 返回 `{"status":"ok","version":"1.6.0"}`；tunnel 日志见 `Registered tunnel connection` × 4，不再有 `trycloudflare.com`。

> TOKEN 明文在服务器 `.env`，能 SSH 进来的人能看到，够用。泄露了在 CF 后台删隧道重建即可。

## 容量评估（6Mbps 带宽瓶颈）

| 场景 | 能扛 |
|---|---|
| 同时浏览/提问 | ~30-50 人并发流畅 |
| 同时传书 | 2-3 人并发（KG 抽取吃 2 核 CPU，多了排队） |
| 日活 | 几百人错峰无压力 |

真火了**第一个加带宽**：腾讯云控制台 6Mbps→10Mbps 几十元/月，立刻翻倍。CPU/内存 2核4G 短期不用动。单 worker 同步处理，超 ~50 并发请求会排队（变慢不崩），到这一步才考虑加实例。

## 运维命令（在服务器 `~/BookScope` 下）

```bash
# 看状态
docker compose ps
curl -fsS http://127.0.0.1:8000/api/health

# 看日志
docker compose logs api --tail 50
docker compose logs tunnel --tail 30

# 重启
docker compose restart api
docker compose up -d            # 改了 .env 后重启 tunnel

# 更新代码（GitHub 拉最新，国内 git pull 抖就用 ghproxy）
git pull --ff-only
# 或：git pull --ff-only https://gh-proxy.com/https://github.com/moyu-good/BookScope.git main
docker compose up -d --build

# 备份（data 目录 = session 存档 + 缓存 SQLite，服务器挂了没备份就全没）
mkdir -p /root/backup
tar czf /root/backup/bookscope-$(date +%F).tar.gz /root/BookScope/data
# cron 每天凌晨 3 点备份、保留 7 天：
# 0 3 * * * tar czf /root/backup/bookscope-$(date +\%F).tar.gz /root/BookScope/data && find /root/backup -name "bookscope-*.tar.gz" -mtime +7 -delete
```

持久化验证：`docker compose restart api` 后刷新页面，书架里的书还在 = `./data:/app/data` 卷挂载生效。

## 相关文件

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 多阶段：node:22 构前端 → python:3.12-slim 跑后端（3.12 因 faiss-cpu 无 3.14 wheel） |
| `docker-compose.yml` | api + cloudflared tunnel 两服务，`./data` 挂卷持久化 |
| `deploy/deploy-on-tencent.sh` | 服务器侧一键部署脚本（带规格自检） |
| `bookscope/api/middleware.py` | `AbuseGuardMiddleware`：上传封顶 50MB + IP 令牌桶限流（零依赖 ASGI，slowapi 与 File/Form 端点签名不兼容故自写） |
| `bookscope/api/app.py` | 挂中间件 + `SPAStaticFiles` 同源托管前端 + CORS 读 env |
| `.env.example` | 部署变量模板（TUNNEL_TOKEN/TUNNEL_CMD/MAX_UPLOAD_MB/CORS） |
