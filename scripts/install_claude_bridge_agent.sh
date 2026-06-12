#!/usr/bin/env bash
#
# Install (or uninstall) a macOS LaunchAgent that auto-starts the Claude Code
# bridge (scripts/claude_bridge.py) on login, so the Strategy Lab chat works
# without manually keeping a terminal open.
#
#   ./scripts/install_claude_bridge_agent.sh          # install + start
#   ./scripts/install_claude_bridge_agent.sh --uninstall
#
# The bridge needs the `claude` CLI on PATH and reads CLAUDE_BRIDGE_TOKEN from
# the repo .env. The generated plist lives in ~/Library/LaunchAgents and is NOT
# committed (it can contain the token).

set -euo pipefail

LABEL="com.loaded.claude-bridge"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

uninstall() {
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $PLIST and unloaded the agent."
  exit 0
}

[[ "${1:-}" == "--uninstall" ]] && uninstall

# ── Resolve dependencies ──────────────────────────────────────────────────────
CLAUDE_BIN="$(command -v claude || true)"
if [[ -z "$CLAUDE_BIN" ]]; then
  echo "ERROR: 'claude' CLI not found on PATH. Install/auth Claude Code first." >&2
  exit 1
fi
CLAUDE_DIR="$(dirname "$CLAUDE_BIN")"
PYTHON_BIN="$(command -v python3)"

PORT="$(grep -E '^CLAUDE_BRIDGE_PORT=' "$REPO/.env" 2>/dev/null | cut -d= -f2 || true)"
PORT="${PORT:-8787}"
TOKEN="$(grep -E '^CLAUDE_BRIDGE_TOKEN=' "$REPO/.env" 2>/dev/null | cut -d= -f2- || true)"

# Stop any bridge already bound to the port (manual run or a prior agent).
launchctl unload "$PLIST" 2>/dev/null || true
pkill -f "scripts/claude_bridge.py" 2>/dev/null || true
sleep 1

# ── Write the plist ───────────────────────────────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${REPO}/scripts/claude_bridge.py</string>
  </array>
  <key>WorkingDirectory</key><string>${REPO}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>${CLAUDE_DIR}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>CLAUDE_BRIDGE_PORT</key><string>${PORT}</string>
    <key>CLAUDE_BRIDGE_TOKEN</key><string>${TOKEN}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/claude_bridge.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/claude_bridge.err.log</string>
</dict>
</plist>
PLIST

launchctl load "$PLIST"
echo "Installed + loaded: $PLIST"
echo "  python: $PYTHON_BIN"
echo "  claude: $CLAUDE_BIN"
echo "  port:   $PORT  (token: $([[ -n "$TOKEN" ]] && echo set || echo none))"
echo "  logs:   /tmp/claude_bridge.out.log  /tmp/claude_bridge.err.log"
echo
echo "Verify:  curl -s http://localhost:${PORT}/health"
