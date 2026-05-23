#!/usr/bin/env bash
set -euo pipefail

ENV_PATH="${N8N_MCP_ENV:-$HOME/.config/n8n-mcp/env}"
install -d -m 700 "$(dirname "$ENV_PATH")"

printf 'n8n base URL [http://127.0.0.1:5678]: ' >&2
IFS= read -r base_url
base_url="${base_url:-http://127.0.0.1:5678}"

printf 'Paste n8n API key: ' >&2
IFS= read -r -s api_key
printf '\n' >&2

if [[ -z "$api_key" ]]; then
  echo 'No API key provided; aborting.' >&2
  exit 1
fi

umask 077
cat > "$ENV_PATH" <<EOF
N8N_BASE_URL=$base_url
N8N_API_KEY=$api_key
N8N_MCP_TIMEOUT=30
N8N_CONTAINER_NAME=n8n
N8N_MCP_ALLOW_DOCKER_LOGS=true
EOF
chmod 600 "$ENV_PATH"
echo "Wrote $ENV_PATH with mode 600."
