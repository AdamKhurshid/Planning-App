"""A defensive MCP (Model Context Protocol) stdio server for Tempo.

Speaks newline-delimited JSON-RPC 2.0 on stdio — the standard MCP stdio
transport — so any MCP client can launch it, e.g.:

    "mcpServers": { "tempo": { "command": "python",
                               "args": ["backend/manage.py", "run_mcp"] } }

The same tool registry backs both this server and the in-app agent, so the
validation guarantees are identical. Defence in depth:

* Malformed JSON, unknown methods, oversized frames and missing fields never
  crash the loop — each becomes a JSON-RPC error response.
* Tool EXECUTION failures are reported as results with isError=true (per MCP
  spec), not protocol errors.
* Arguments are validated by agent.tools.validate_args before anything runs;
  all data access is owner-scoped to the app's single owner user.
* Every mutating tool call is preceded by a full database backup
  (TEMPO-agent backups dir), so damage is always reversible.
"""
from __future__ import annotations

import json
import sys

from . import memory, store, tools

PROTOCOL_VERSION = "2024-11-05"
MAX_FRAME_BYTES = 1_000_000


def _result(req_id, payload: dict):
    return {"jsonrpc": "2.0", "id": req_id, "result": payload}


def _error(req_id, code: int, message: str):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message[:500]}}


def handle(req: dict, owner) -> dict | None:
    """Dispatch one JSON-RPC request. Returns a response dict, or None for
    notifications. Never raises."""
    if not isinstance(req, dict):
        return _error(None, -32600, "Request must be a JSON object.")
    method = req.get("method")
    req_id = req.get("id")
    is_notification = req_id is None and isinstance(method, str) and method.startswith("notifications/")

    try:
        if method == "initialize":
            return _result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tempo", "version": "1.0.0"},
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None  # notifications get no response
        if method == "ping":
            return _result(req_id, {})
        if method == "tools/list":
            return _result(req_id, {"tools": tools.tool_specs()})
        if method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(name, str) or not name:
                return _error(req_id, -32602, "params.name must be a tool name string.")
            if owner is None:
                return _result(req_id, {"content": [{"type": "text", "text":
                            "No owner user exists yet — log into Tempo once, then retry."}],
                            "isError": True})
            outcome = tools.call_tool(owner, name, arguments)
            text = json.dumps(outcome, ensure_ascii=False)
            return _result(req_id, {"content": [{"type": "text", "text": text[:8000]}],
                                    "isError": not outcome.get("ok", False)})
        if is_notification:
            return None
        return _error(req_id, -32601, f"Unknown method: {method!r}")
    except Exception as exc:  # absolutely nothing escapes the dispatch
        return _error(req_id, -32603, f"Internal error: {type(exc).__name__}: {exc}")


def serve(reader=None, writer=None) -> None:
    """Main loop. Never exits on bad input; exits cleanly on EOF."""
    reader = reader or sys.stdin
    writer = writer or sys.stdout
    owner = tools.owner_user()
    memory.register_tools(tools.TOOLS)
    while True:
        line = reader.readline()
        if not line:
            break
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.strip()
        if not line:
            continue
        if len(line) > MAX_FRAME_BYTES:
            resp = _error(None, -32700, "Frame too large.")
        else:
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                resp = _error(None, -32700, f"Parse error: {exc.msg}")
            except Exception as exc:
                resp = _error(None, -32700, f"Parse error: {exc}")
            else:
                resp = handle(req, owner)
        if resp is None:
            continue
        try:
            writer.write(json.dumps(resp, ensure_ascii=False) + "\n")
            writer.flush()
        except Exception:
            break


if __name__ == "__main__":
    serve()
