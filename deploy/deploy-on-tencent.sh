#!/usr/bin/env bash
# BookScope 腾讯云一键部署脚本。
#
# 用法（在腾讯云服务器上，root 或 sudo 用户）：
#   bash deploy/deploy-on-tencent.sh
#
# 做的事：规格自检 → 装 Docker → 克隆/更新仓库 → 起容器 → 报临时 URL。
# 正式域名（bookscope.top）见脚本末尾提示，要在 Cloudflare Zero Trust 配。

set -euo pipefail

REPO_URL="https://github.com/moyu-good/BookScope.git"
REPO_DIR="BookScope"

echo "═══════════════════════════════════════════════════════"
echo "  BookScope 部署 —— 规格自检"
echo "═══════════════════════════════════════════════════════"

# ── 内存自检 ──
mem_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
echo "内存：${mem_mb} MB"
if [ "$mem_mb" -lt 1024 ]; then
    echo "✗ 内存 <1GB，大书 KG 抽取 + FAISS 必 OOM，不部署。加内存再来。"
    exit 1
elif [ "$mem_mb" -lt 2048 ]; then
    echo "⚠ 内存 <2GB，中小书能跑、几百万字大书可能 OOM，谨慎。"
else
    echo "✓ 内存 ≥2GB，大书可跑。"
fi

echo "磁盘："; df -h /
echo "CPU 核数：$(nproc)"

# ── DeepSeek 连通性（BYOK 下服务器要能调 DeepSeek）──
echo -n "DeepSeek 连通性："
ds_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://api.deepseek.com || true)
if [ "$ds_code" = "000" ] || [ -z "$ds_code" ]; then
    echo "不通（超时）。BYOK 下访客 key 会经服务器调 DeepSeek，不通则功能不可用——检查网络/安全组出站。"
else
    echo "HTTP $ds_code（连通）"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  1/4  装 Docker"
echo "═══════════════════════════════════════════════════════"
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    echo "✓ Docker 装好"
else
    echo "✓ Docker 已装：$(docker --version)"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  2/4  拉代码"
echo "═══════════════════════════════════════════════════════"
if [ -d "$REPO_DIR" ]; then
    echo "已存在 $REPO_DIR，git pull 更新..."
    cd "$REPO_DIR" && git pull --ff-only
else
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  3/4  配 .env"
echo "═══════════════════════════════════════════════════════"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "已从 .env.example 复制 .env（临时隧道模式，无需填 token）"
else
    echo ".env 已存在，跳过"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  4/4  构建并启动"
echo "═══════════════════════════════════════════════════════"
docker compose up -d --build

echo ""
echo "等待 API 起来..."
for i in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        echo "✓ API 健康：$(curl -fsS http://127.0.0.1:8000/api/health)"
        break
    fi
    sleep 2
done

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  临时公网 URL（*.trycloudflare.com）"
echo "═══════════════════════════════════════════════════════"
echo "等约 10-30 秒隧道建立，然后看日志里的 URL："
echo "  docker compose logs tunnel | grep -i trycloudflare"
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  切到正式域名 bookscope.top（免备案）"
echo "═══════════════════════════════════════════════════════"
echo "1. 买域名 bookscope.top（Cloudflare Registrar 最省，DNS 直接在 CF）"
echo "2. Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel"
echo "   → 复制 TOKEN → 填进 .env 的 TUNNEL_TOKEN="
echo "   → .env 里改 TUNNEL_CMD=tunnel run --token <你的TOKEN>"
echo "3. 隧道里配 Public Hostname：bookscope.top → Service: http://api:8000"
echo "4. docker compose up -d  重启 tunnel 服务"
echo "5. 访问 https://bookscope.top —— HTTPS 自动、免备案"
