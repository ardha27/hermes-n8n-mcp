# Hermes n8n MCP

Local stdio MCP bridge for managing n8n from Hermes Agent.

This is the sanitized public version of the bridge built for a production VPS. It gives Hermes n8n tools without exposing n8n over the public internet and without putting API keys in your Hermes config.

## What it does

Exposes these MCP tools:

- `health` — check n8n API reachability and optional Docker container status
- `list_workflows` — list workflows, optionally filtered by active state
- `get_workflow` — inspect one workflow with secret-bearing fields redacted
- `find_workflows` — search workflow metadata
- `list_executions` — list recent executions
- `get_execution` — inspect one execution; payload data is off by default
- `recent_failures` — recent failed/error executions
- `export_workflow` — fetch redacted workflow JSON for backup/review
- `activate_workflow` — activate a workflow by ID
- `deactivate_workflow` — deactivate a workflow by ID
- `create_workflow` — create a new workflow from JSON definition
- `update_workflow` — patch an existing workflow by ID
- `trigger_execution` — manually trigger a workflow run
- `delete_workflow` — delete a workflow by ID
- `container_logs` — optional Docker logs with line-level redaction

## Security posture

- Stdio only. No HTTP server. No public port.
- API key is loaded from environment or a local dotenv file.
- `.env` is gitignored.
- Example config uses `REPLACE_ME`, never a real key.
- Tool responses redact obvious credential, token, secret, password, and authorization fields.
- Execution payload data is disabled by default in `get_execution`.
- Workflow activation/deactivation are production mutations. Treat them like loaded weapons.

## Requirements

- Python 3.10+
- Hermes Agent with native MCP enabled
- n8n API key
- n8n reachable from the machine running Hermes, usually `http://127.0.0.1:5678`

## Install

```bash
git clone https://github.com/CyberSamuraiX/hermes-n8n-mcp.git
cd hermes-n8n-mcp
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Store your n8n key

Interactive helper:

```bash
./scripts/set-key.sh
```

Default output path:

```text
~/.config/n8n-mcp/env
```

Expected permissions:

```bash
stat -c '%a %U:%G %n' ~/.config/n8n-mcp/env
# 600 youruser:yourgroup /home/youruser/.config/n8n-mcp/env
```

Manual version:

```bash
install -d -m 700 ~/.config/n8n-mcp
cat > ~/.config/n8n-mcp/env <<'EOF'
N8N_BASE_URL=http://127.0.0.1:5678
N8N_API_KEY=REPLACE_ME
N8N_MCP_TIMEOUT=30
N8N_CONTAINER_NAME=n8n
N8N_MCP_ALLOW_DOCKER_LOGS=true
EOF
chmod 600 ~/.config/n8n-mcp/env
```

Replace `REPLACE_ME` locally. Do not commit the real file.

## Hermes config

Add this to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  n8n:
    command: "/absolute/path/to/hermes-n8n-mcp/.venv/bin/python"
    args:
      - "/absolute/path/to/hermes-n8n-mcp/server.py"
    env:
      N8N_MCP_ENV: "/absolute/path/to/.config/n8n-mcp/env"
    timeout: 120
    connect_timeout: 30
    sampling:
      enabled: false
```

Then reload MCP in Hermes:

```text
/reload-mcp
```

Or from shell:

```bash
hermes mcp test n8n
```

## Smoke test outside Hermes

```bash
. .venv/bin/activate
python -m py_compile server.py
hermes mcp test n8n
```

## Docker logs

`container_logs` shells out to Docker. If the user running Hermes cannot access Docker, set:

```text
N8N_MCP_ALLOW_DOCKER_LOGS=false
```

The rest of the API tools will still work.

## Notes for production use

- Keep n8n bound to loopback behind your reverse proxy.
- Do not expose this MCP bridge over Caddy, nginx, or Docker ports.
- Rotate n8n API keys if they ever hit chat logs, terminals, CI output, screenshots, or issue trackers.
- Back up workflows before mutating them.

## License

MIT. See `LICENSE`.
