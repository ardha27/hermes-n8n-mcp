#!/usr/bin/env python3
"""Local stdio MCP bridge for n8n.

This server lets Hermes Agent manage an n8n instance through n8n's public API
without exposing your API key or opening a network listener.

Transport: stdio only.
Secrets: loaded from env or a root/user-owned dotenv file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

DEFAULT_ENV_PATHS = [
    Path(os.getenv("N8N_MCP_ENV", "")) if os.getenv("N8N_MCP_ENV") else None,
    Path.home() / ".config" / "n8n-mcp" / "env",
    Path.cwd() / ".env",
]

for env_path in DEFAULT_ENV_PATHS:
    if env_path and env_path.exists():
        load_dotenv(env_path)
        break

BASE_URL = os.getenv("N8N_BASE_URL", "http://127.0.0.1:5678").rstrip("/")
API_KEY = os.getenv("N8N_API_KEY", "")
TIMEOUT = float(os.getenv("N8N_MCP_TIMEOUT", "30"))
CONTAINER_NAME = os.getenv("N8N_CONTAINER_NAME", "n8n")
ALLOW_DOCKER_LOGS = os.getenv("N8N_MCP_ALLOW_DOCKER_LOGS", "true").lower() in {"1", "true", "yes", "on"}

mcp = FastMCP("n8n")

SECRET_KEY_RE = re.compile(r"(password|secret|token|apikey|api_key|credential|authorization|bearer)", re.I)
SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+)[A-Za-z0-9._~+/=-]+|"
    r"(sk-[A-Za-z0-9_-]{16,})|"
    r"(gh[pousr]_[A-Za-z0-9_]{16,})|"
    r"(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)


def _redact_string(value: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: (m.group(1) or "") + "[REDACTED]", value)


def _safe(obj: Any) -> Any:
    """Redact obvious secret-bearing fields before returning data to the model."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if SECRET_KEY_RE.search(str(k)):
                out[k] = "[REDACTED]"
            else:
                out[k] = _safe(v)
        return out
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    if isinstance(obj, str):
        return _redact_string(obj)
    return obj


def _headers() -> dict[str, str]:
    if not API_KEY or API_KEY == "REPLACE_ME":
        raise RuntimeError(
            "N8N_API_KEY is missing. Set it in the environment or in ~/.config/n8n-mcp/env."
        )
    return {
        "X-N8N-API-KEY": API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, headers=_headers(), timeout=TIMEOUT)


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    with _client() as c:
        r = c.request(method, path, **kwargs)
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text[:2000]}
        if r.status_code >= 400:
            return {"ok": False, "status_code": r.status_code, "error": _safe(data)}
        return {"ok": True, "status_code": r.status_code, "data": _safe(data)}


def _rows_from_list_response(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    if isinstance(data, dict):
        rows = data.get("data") or data.get("workflows") or data.get("executions") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


@mcp.tool()
def health() -> dict[str, Any]:
    """Check local n8n API reachability and optional Docker container status."""
    result: dict[str, Any] = {
        "base_url": BASE_URL,
        "api_key_configured": bool(API_KEY and API_KEY != "REPLACE_ME"),
    }
    try:
        with _client() as c:
            r = c.get("/api/v1/workflows", params={"limit": 1})
            result["api_status_code"] = r.status_code
            result["api_ok"] = r.status_code < 400
    except Exception as e:
        result["api_ok"] = False
        result["api_error"] = str(e)

    if ALLOW_DOCKER_LOGS:
        try:
            ps = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    f"name=^/{CONTAINER_NAME}$",
                    "--format",
                    "{{.Names}} {{.Status}} {{.Ports}}",
                ],
                text=True,
                capture_output=True,
                timeout=10,
            )
            result["container"] = ps.stdout.strip() or "not found"
        except Exception as e:
            result["container_error"] = str(e)
    return result


@mcp.tool()
def list_workflows(active: bool | None = None, limit: int = 100) -> dict[str, Any]:
    """List workflows. Optional active filter."""
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 250))}
    if active is not None:
        params["active"] = str(bool(active)).lower()
    return _request("GET", "/api/v1/workflows", params=params)


@mcp.tool()
def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Get one workflow by ID. Credential-bearing fields are redacted."""
    return _request("GET", f"/api/v1/workflows/{workflow_id}")


@mcp.tool()
def find_workflows(query: str, limit: int = 100) -> dict[str, Any]:
    """Search workflows by name/id/tag in the workflow list."""
    res = list_workflows(limit=limit)
    if not res.get("ok"):
        return res
    q = query.lower()
    matches = []
    for wf in _rows_from_list_response(res):
        hay = json.dumps(_safe(wf), ensure_ascii=False).lower()
        if q in hay:
            matches.append(wf)
    return {"ok": True, "data": matches, "count": len(matches)}


@mcp.tool()
def list_executions(workflow_id: str | None = None, status: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List recent executions. Optional workflow_id and status filters."""
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 250))}
    if workflow_id:
        params["workflowId"] = workflow_id
    if status:
        params["status"] = status
    return _request("GET", "/api/v1/executions", params=params)


@mcp.tool()
def get_execution(execution_id: str, include_data: bool = False) -> dict[str, Any]:
    """Get execution details. include_data defaults false to avoid leaking payload data."""
    params = {"includeData": str(bool(include_data)).lower()}
    return _request("GET", f"/api/v1/executions/{execution_id}", params=params)


@mcp.tool()
def recent_failures(limit: int = 25) -> dict[str, Any]:
    """Return recent failed/error executions for triage."""
    return list_executions(status="error", limit=limit)


@mcp.tool()
def export_workflow(workflow_id: str) -> dict[str, Any]:
    """Fetch workflow JSON for backup/export with credential-bearing fields redacted."""
    return get_workflow(workflow_id)


@mcp.tool()
def activate_workflow(workflow_id: str) -> dict[str, Any]:
    """Activate a workflow by ID. Treat as a production mutation."""
    return _request("POST", f"/api/v1/workflows/{workflow_id}/activate")


@mcp.tool()
def deactivate_workflow(workflow_id: str) -> dict[str, Any]:
    """Deactivate a workflow by ID. Treat as a production mutation."""
    return _request("POST", f"/api/v1/workflows/{workflow_id}/deactivate")


@mcp.tool()
def container_logs(lines: int = 100) -> dict[str, Any]:
    """Return recent Docker logs with simple redaction, if Docker log access is enabled."""
    if not ALLOW_DOCKER_LOGS:
        return {"ok": False, "error": "Docker log access disabled by N8N_MCP_ALLOW_DOCKER_LOGS=false"}
    n = max(1, min(int(lines), 500))
    try:
        p = subprocess.run(
            ["docker", "logs", "--tail", str(n), CONTAINER_NAME],
            text=True,
            capture_output=True,
            timeout=20,
        )
        text = p.stdout + p.stderr
        redacted_lines = []
        for line in text.splitlines():
            if SECRET_KEY_RE.search(line):
                redacted_lines.append("[REDACTED SECRET-BEARING LOG LINE]")
            else:
                redacted_lines.append(_redact_string(line))
        return {"ok": p.returncode == 0, "exit_code": p.returncode, "logs": "\n".join(redacted_lines[-n:])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def create_workflow(
    name: str,
    nodes: list[dict[str, Any]],
    connections: dict[str, Any] | None = None,
    active: bool = False,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new n8n workflow. `nodes` and `connections` must follow n8n workflow JSON shape."""
    if not name.strip():
        return {"ok": False, "error": "name is required"}
    payload: dict[str, Any] = {"name": name.strip(), "nodes": nodes, "active": bool(active)}
    if connections is not None:
        payload["connections"] = connections
    if tags is not None:
        payload["tags"] = tags
    return _request("POST", "/api/v1/workflows", json=payload)


@mcp.tool()
def update_workflow(
    workflow_id: str,
    name: str | None = None,
    nodes: list[dict[str, Any]] | None = None,
    connections: dict[str, Any] | None = None,
    active: bool | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing workflow by ID. Only provided fields are patched."""
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if nodes is not None:
        payload["nodes"] = nodes
    if connections is not None:
        payload["connections"] = connections
    if active is not None:
        payload["active"] = bool(active)
    if tags is not None:
        payload["tags"] = tags
    if not payload:
        return {"ok": False, "error": "No fields provided to update"}
    return _request("PUT", f"/api/v1/workflows/{workflow_id}", json=payload)


@mcp.tool()
def trigger_execution(workflow_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Manually trigger an execution for an existing workflow.
    `data` is optional input payload for the workflow run."""
    if not workflow_id.strip():
        return {"ok": False, "error": "workflow_id is required"}
    payload: dict[str, Any] = {}
    if data is not None:
        payload["data"] = data
    return _request("POST", f"/api/v1/workflows/{workflow_id}/executions", json=payload)


@mcp.tool()
def delete_workflow(workflow_id: str) -> dict[str, Any]:
    """Delete a workflow by ID. This is destructive."""
    if not workflow_id.strip():
        return {"ok": False, "error": "workflow_id is required"}
    return _request("DELETE", f"/api/v1/workflows/{workflow_id}")


if __name__ == "__main__":
    mcp.run()
