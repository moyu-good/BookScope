#!/usr/bin/env bash
# 应用 CI workflow 修复补丁（Python 3.12 + 稳定 action 版本）。
# 当前推送 token 没有 workflow scope 时无法直接推 .github/workflows，
# 先本地应用，等有权限后提交推送即可。
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f docs/ci-workflow-fixes.patch ]; then
  echo "找不到 docs/ci-workflow-fixes.patch" >&2
  exit 1
fi
git apply docs/ci-workflow-fixes.patch
echo "已应用 CI workflow 补丁。请 review 后提交推送："
echo "  git add .github/workflows && git commit && git push"
