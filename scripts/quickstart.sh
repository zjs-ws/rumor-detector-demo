#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== RumorBuster V2.1 Quick Start =="

COMPOSE=(docker compose -f compose.prod.yaml)

command -v docker >/dev/null 2>&1 || {
  echo "❌ 未安装 Docker"
  exit 1
}

command -v curl >/dev/null 2>&1 || {
  echo "❌ 未安装 curl"
  exit 1
}

docker info >/dev/null 2>&1 || {
  echo "❌ Docker 未运行，请先启动 Docker Desktop"
  exit 1
}

"${COMPOSE[@]}" version >/dev/null 2>&1 || {
  echo "❌ Docker Compose 不可用"
  exit 1
}

if [[ ! -f .env ]]; then
  cp -n .env.example .env
  chmod 600 .env
  echo "⚠️ 已创建 .env，请填写自己的 DEEPSEEK_API_KEY 后重新运行"
  exit 1
fi

if grep -q 'your_deepseek_api_key_here' .env ||
   ! grep -Eq '^DEEPSEEK_API_KEY=.{10,}$' .env; then
  echo "❌ .env 中的 DEEPSEEK_API_KEY 尚未正确配置"
  exit 1
fi

if grep -q 'your_tavily_api_key_here' .env ||
   ! grep -Eq '^TAVILY_API_KEY=.{10,}$' .env; then
  echo "⚠️  未检测到 TAVILY_API_KEY：搜索和网页抓取将不可用，核验会因缺少证据而失败。"
  echo "    免费注册 https://tavily.com ，把 key 填进 .env 后重新运行本脚本。"
  exit 1
fi

if [[ ! -f config.yaml ]]; then
  cp -n config.example.yaml config.yaml
  echo "✅ 已创建 config.yaml"
fi

mkdir -p runtime/checkpoints
chmod 755 runtime runtime/checkpoints

"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" up -d --build

HTTP_PORT="$("${COMPOSE[@]}" port nginx 80 2>/dev/null | sed -E 's/.*:([0-9]+)$/\1/' | tail -n 1)"
if [[ ! "$HTTP_PORT" =~ ^[0-9]+$ ]]; then
  HTTP_PORT=8080
fi
BASE_URL="http://127.0.0.1:${HTTP_PORT}"

echo "等待服务启动……"
for _ in $(seq 1 90); do
  if curl -fsS "${BASE_URL}/healthz" >/dev/null 2>&1 &&
     curl -fsS "${BASE_URL}/workspace/chats/new" >/dev/null 2>&1; then
    echo "✅ 启动成功"
    "${COMPOSE[@]}" ps
    echo "RumorBuster: ${BASE_URL}/workspace/chats/new"
    echo "健康检查: ${BASE_URL}/healthz"
    echo "统一核验 API: ${BASE_URL}/api/v1/checks"
    exit 0
  fi
  sleep 2
done

echo "❌ 服务未在规定时间内通过健康检查"
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=120 nginx frontend gateway langgraph
exit 1
