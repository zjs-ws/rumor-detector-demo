#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
  pwd
)"
LOCAL_ENV="${PROJECT_ROOT}/.claude/deepseek.env"
PROJECT_ENV="${PROJECT_ROOT}/.env"

if [[ -f "${LOCAL_ENV}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL_ENV}"
  set +a
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" && -f "${PROJECT_ENV}" ]]; then
  DEEPSEEK_API_KEY="$(
    sed -n 's/^[[:space:]]*DEEPSEEK_API_KEY[[:space:]]*=[[:space:]]*//p' \
      "${PROJECT_ENV}" \
      | tail -n 1
  )"
  DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY%\"}"
  DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY#\"}"
  DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY%\'}"
  DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY#\'}"
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" \
   || "${DEEPSEEK_API_KEY}" == "your_deepseek_api_key_here" ]]; then
  cat >&2 <<'EOF'
DeepSeek API Key 未配置。

请任选一种方式：
1. 在项目根目录 .env 中填写 DEEPSEEK_API_KEY；
2. cp .claude/deepseek.env.example .claude/deepseek.env，然后填写 Key；
3. 启动前 export DEEPSEEK_API_KEY=你的Key。
EOF
  exit 1
fi

PRIMARY_MODEL="${DEEPSEEK_CLAUDE_PRIMARY_MODEL:-deepseek-v4-pro[1m]}"
FAST_MODEL="${DEEPSEEK_CLAUDE_FAST_MODEL:-deepseek-v4-flash}"

# DeepSeek exposes an Anthropic Messages compatible endpoint specifically for
# clients such as Claude Code. The token is intentionally injected only into
# this process and is never written to a tracked settings file.
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="${DEEPSEEK_API_KEY}"
unset ANTHROPIC_API_KEY

export ANTHROPIC_MODEL="${PRIMARY_MODEL}"
export ANTHROPIC_DEFAULT_OPUS_MODEL="${PRIMARY_MODEL}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="${PRIMARY_MODEL}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${FAST_MODEL}"
export CLAUDE_CODE_SUBAGENT_MODEL="${FAST_MODEL}"
export CLAUDE_CODE_EFFORT_LEVEL="${DEEPSEEK_CLAUDE_EFFORT:-max}"

cd "${PROJECT_ROOT}"
exec claude "$@"
