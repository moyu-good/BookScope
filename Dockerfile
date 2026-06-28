# syntax=docker/dockerfile:1

# ── stage 1: 构前端 ──────────────────────────────────────────────
# 非 demo 模式（base="/"）构建，产物 web/dist 同源托管。
FROM node:22-slim AS web
WORKDIR /app/web
# 先拷清单，利用层缓存（WORKDIR 已是 /app/web，目标用 ./ 拷进当前目录，
# 别写 web/xxx —— 那会解析成 /app/web/web/xxx 多一层，npm install 找不到 package.json）
COPY web/package.json ./
COPY web/vite.config.ts ./
COPY web/tsconfig.json ./
COPY web/tsconfig.node.json ./
COPY web/index.html ./
COPY web/src ./src
COPY web/public ./public
# npm 换淘宝源：国内服务器走 npm 默认源慢。
RUN npm install --no-audit --no-fund --registry=https://registry.npmmirror.com && npm run build


# ── stage 2: 运行时 ──────────────────────────────────────────────
# python:3.12-slim：faiss-cpu 没有 3.14 预编译 wheel，4G 服务器从源码编译会 OOM
# （这是首次部署卡死一小时的根因）；3.12 有 wheel，pip 秒装。pyproject 要求 >=3.12。
FROM python:3.12-slim AS runtime

# 系统依赖：build-essential 给 faiss-cpu/numpy 编译兜底；libgomp1 是
# FAISS/OpenBLAS 运行时必需（slim 镜像默认没有，缺了 import faiss 就崩）。
# git：部分包可能从 git 装；curl：healthcheck 用。
# apt 换清华源：国内服务器（腾讯云）走默认 Debian 源很慢，换源省一大半时间。
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存：只 pyproject 变才重装）
# pip 换清华源：国内服务器走 PyPI 默认源慢，且 faiss-cpu wheel 体积大。
COPY pyproject.toml ./
COPY README.md ./
COPY bookscope/__init__.py bookscope/__init__.py
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple ".[docx]"
# 注：限流用自写 AbuseGuardMiddleware（零依赖），不装 slowapi——其装饰器与
# 新版 fastapi 对 File/Form 端点签名解析不兼容。

# 下 NLTK 语料（nrclex/textblob 运行时需要）。
# 默认 NLTK 源是 raw.githubusercontent.com，国内服务器拉要 20+ 分钟；换 ghproxy 镜像几十秒。
# 下 nrclex/textblob 实际用到的最小集：punkt 分词 + perceptron tagger 词性 + wordnet/brown 兜底。
# （punkt_tab / tagger_eng 是 nltk>=3.9 的新名，新旧都下保险；不装 conll2000/movie_reviews——nrclex 用不到。）
ENV NLTK_DATA=/usr/local/nltk_data
RUN set -eux; \
    mkdir -p /usr/local/nltk_data/tokenizers /usr/local/nltk_data/taggers /usr/local/nltk_data/corpora; \
    NLTK_PKGS="tokenizers/punkt tokenizers/punkt_tab taggers/averaged_perceptron_tagger taggers/averaged_perceptron_tagger_eng corpora/wordnet corpora/brown"; \
    MIRRORS="https://gh-proxy.com/https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages https://ghproxy.net/https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages"; \
    for pkg in $NLTK_PKGS; do \
      dir=$(dirname "$pkg"); name=$(basename "$pkg"); ok=0; \
      for m in $MIRRORS; do \
        if curl -fsSL "$m/$pkg.zip" -o /tmp/$name.zip; then \
          python -c "import zipfile; zipfile.ZipFile('/tmp/$name.zip').extractall('/usr/local/nltk_data/$dir')" && rm /tmp/$name.zip && ok=1 && break; \
        fi; \
      done; \
      [ "$ok" = "1" ] || { echo "NLTK 语料下载失败: $pkg"; exit 1; }; \
    done

# 拷业务代码
COPY bookscope bookscope

# 拷前端构建产物
COPY --from=web /app/web/dist /app/static

# 持久化目录：session 存档 + 各级缓存 SQLite。挂卷到这。
RUN mkdir -p /app/data/.bookscope_cache
ENV BOOKSCOPE_STATIC_DIR=/app/static \
    BOOKSCOPE_BOOK_CACHE_DIR=/app/data/.bookscope_cache/book_warmup \
    BOOKSCOPE_LLM_CACHE_DB_PATH=/app/data/.bookscope_cache/llm_cache.db \
    BOOKSCOPE_KG_CACHE_DB_PATH=/app/data/.bookscope_cache/kg_cache.db \
    BOOKSCOPE_SPINE_CACHE_DB_PATH=/app/data/.bookscope_cache/kg_cache.db \
    BOOKSCOPE_DOC_SPINE_CACHE_DB_PATH=/app/data/.bookscope_cache/kg_cache.db \
    BOOKSCOPE_KG_BOOK_CACHE_DB_PATH=/app/data/.bookscope_cache/kg_cache.db \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# 单 worker（BookSessionStore 是进程级单例，多 worker 会 session 错位）。
# --proxy-headers --forwarded-allow-ips=*：从 Cloudflare 隧道的 X-Forwarded-For
# / CF-Connecting-IP 还原真实访客 IP，限流才有效。
CMD ["uvicorn", "bookscope.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
