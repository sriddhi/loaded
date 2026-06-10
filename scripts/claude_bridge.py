#!/usr/bin/env python3
"""
Claude Code bridge — a tiny host-side HTTP shim so the dockerized backend can use
your local Claude Code subscription instead of a funded Anthropic API key.

Why this exists: on macOS, Claude Code stores its auth in the Keychain, which a
Docker container can't reach. This process runs on the HOST (where `claude` is
authenticated) and exposes one endpoint the backend calls:

    POST /chat   { "system": "...", "prompt": "...", "model": "opus|sonnet|..." }
      -> { "text": "<assistant reply>" }

It shells out to `claude -p --output-format json` per request (stateless), in an
isolated temp dir with tools disabled, so it behaves as a plain LLM completion.

Run it on your Mac (NOT in Docker):

    python3 scripts/claude_bridge.py            # binds 0.0.0.0:8787
    CLAUDE_BRIDGE_TOKEN=secret python3 scripts/claude_bridge.py   # require a token

Stop it with Ctrl-C. To switch the app back to the API key, set
STRATEGY_CHAT_PROVIDER=api in .env and restart the backend — this bridge is no
longer used.

Stdlib only (no pip installs); requires the `claude` CLI on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CLAUDE_BRIDGE_PORT", "8787"))
TOKEN = os.environ.get("CLAUDE_BRIDGE_TOKEN", "")
CLAUDE_BIN = shutil.which("claude") or os.path.expanduser("~/.claude/local/claude")


def _run_claude(system: str, prompt: str, model: str | None) -> str:
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if system:
        cmd += ["--append-system-prompt", system]
    if model:
        cmd += ["--model", model]
    # Isolated, tool-free completion: run in an empty temp dir.
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=180, check=False
        )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:500]}")
    data = json.loads(proc.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude error: {data.get('result')}")
    return str(data.get("result", ""))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # health check
        if self.path == "/health":
            self._send(200, {"ok": True, "claude": bool(CLAUDE_BIN)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/chat":
            self._send(404, {"error": "not found"})
            return
        if TOKEN and self.headers.get("X-Bridge-Token") != TOKEN:
            self._send(401, {"error": "bad token"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length) or b"{}")
            text = _run_claude(req.get("system", ""), req.get("prompt", ""), req.get("model"))
            self._send(200, {"text": text})
        except Exception as exc:  # noqa: BLE001
            self._send(502, {"error": str(exc)})

    def log_message(self, *_args: object) -> None:  # quiet
        return


def main() -> None:
    if not CLAUDE_BIN or not os.path.exists(CLAUDE_BIN):
        raise SystemExit("`claude` CLI not found on PATH — install/auth Claude Code first.")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    auth = "token-protected" if TOKEN else "no token (set CLAUDE_BRIDGE_TOKEN to lock down)"
    print(f"[claude-bridge] listening on 0.0.0.0:{PORT} ({auth}); claude={CLAUDE_BIN}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[claude-bridge] stopped")


if __name__ == "__main__":
    main()
