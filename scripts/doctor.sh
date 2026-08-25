#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f compose.prod.yaml)

failed=0

pass() { echo "✅ $1"; }
warn() { echo "⚠️ $1"; }
fail() { echo "❌ $1"; failed=1; }

echo "== RumorBuster Doctor =="

command -v docker >/dev/null 2>&1 && pass "Docker 已安装" || fail "Docker 未安装"
command -v curl >/dev/null 2>&1 && pass "curl 已安装" || fail "curl 未安装"
docker info >/dev/null 2>&1 && pass "Docker 正在运行" || fail "Docker 未运行"
"${COMPOSE[@]}" version >/dev/null 2>&1 && pass "Docker Compose 可用" || fail "Docker Compose 不可用"

[[ -f .env ]] && pass ".env 存在" || warn ".env 不存在"
[[ -f config.yaml ]] && pass "config.yaml 存在" || warn "config.yaml 不存在"
[[ -f compose.prod.yaml ]] && pass "compose.prod.yaml 存在" || fail "compose.prod.yaml 不存在"
[[ -f Dockerfile.local ]] && pass "Dockerfile.local 存在" || fail "Dockerfile.local 不存在"
[[ -f frontend/Dockerfile ]] && pass "前端 Dockerfile 存在" || fail "前端 Dockerfile 不存在"
[[ -f frontend/package.json ]] && pass "前端项目存在" || fail "前端项目不存在"
[[ -f .env.example ]] && pass ".env.example 存在" || fail ".env.example 不存在"
[[ -f config.example.yaml ]] && pass "config.example.yaml 存在" || fail "config.example.yaml 不存在"

git check-ignore -q .env 2>/dev/null &&
  pass ".env 已被 Git 忽略" ||
  fail ".env 没有被 Git 忽略"

git ls-files --error-unmatch .env >/dev/null 2>&1 &&
  fail ".env 正被 Git 跟踪" ||
  pass ".env 未被 Git 跟踪"

if [[ -f .env ]]; then
  if grep -q 'your_deepseek_api_key_here' .env ||
     ! grep -Eq '^DEEPSEEK_API_KEY=.{10,}$' .env; then
    fail "DEEPSEEK_API_KEY 未正确配置"
  else
    pass "DEEPSEEK_API_KEY 已配置"
  fi
fi

if [[ -f .env && -f config.yaml ]]; then
  "${COMPOSE[@]}" config -q >/dev/null 2>&1 &&
    pass "生产 Compose 配置有效" ||
    fail "生产 Compose 配置无效"
fi

echo
echo "疑似密钥文件扫描："
matches="$(
  GIT_PAGER=cat git grep -lE \
  '(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}' \
  -- . 2>/dev/null || true
)"
if [[ -n "$matches" ]]; then
  warn "以下文件包含测试值或疑似密钥，需要人工确认："
  echo "$matches"
else
  pass "未发现常见 sk- 格式密钥"
fi

HTTP_PORT="${RUMORBUSTER_HTTP_PORT:-8080}"
published_port="$("${COMPOSE[@]}" port nginx 80 2>/dev/null | sed -E 's/.*:([0-9]+)$/\1/' | tail -n 1)"
if [[ "$published_port" =~ ^[0-9]+$ ]]; then
  HTTP_PORT="$published_port"
fi
BASE_URL="http://127.0.0.1:${HTTP_PORT}"

curl -fsS "${BASE_URL}/healthz" >/dev/null 2>&1 &&
  pass "统一入口健康检查正常（${BASE_URL}/healthz）" ||
  warn "统一入口当前未运行（${BASE_URL}）"

curl -fsS "${BASE_URL}/workspace/chats/new" >/dev/null 2>&1 &&
  pass "RumorBuster 网页端正常" ||
  warn "RumorBuster 网页端当前未运行"

echo
if [[ "$failed" -eq 0 ]]; then
  echo "✅ 核心检查通过"
else
  echo "❌ 存在需要修复的问题"
  exit 1
fi
