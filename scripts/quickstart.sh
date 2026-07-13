#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Rumor Detector Quick Start =="

command -v docker >/dev/null 2>&1 || {
  echo "❌ 未安装 Docker"
  exit 1
}

docker info >/dev/null 2>&1 || {
  echo "❌ Docker 未运行，请先启动 Docker Desktop"
  exit 1
}

docker compose version >/dev/null 2>&1 || {
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

if [[ ! -f config.yaml ]]; then
  cp -n config.example.yaml config.yaml
  echo "✅ 已创建 config.yaml"
fi

mkdir -p runtime/checkpoints
chmod 755 runtime runtime/checkpoints

docker compose config -q
docker compose up -d --build

echo "等待服务启动……"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8001/health >/dev/null 2>&1 &&
     curl -fsS http://localhost:2024/docs >/dev/null 2>&1; then
    echo "✅ 启动成功"
    docker compose ps
    echo "Gateway: http://localhost:8001/health"
    echo "API Docs: http://localhost:8001/docs"
    exit 0
  fi
  sleep 2
done

echo "❌ 服务未在规定时间内通过健康检查"
docker compose logs --tail=120 langgraph gateway
exit 1
