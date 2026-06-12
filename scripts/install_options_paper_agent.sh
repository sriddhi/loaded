#!/usr/bin/env bash
#
# Install (or uninstall) a macOS LaunchAgent that auto-starts the SPY 0-2 DTE
# options PAPER job on Monday mornings before the open. The job itself only
# trades while the market clock is open and stops at OPT_END_PT.
#
#   ./scripts/install_options_paper_agent.sh            # install (Mondays 06:25 PT)
#   ./scripts/install_options_paper_agent.sh --uninstall
#
# PAPER ONLY — the job hard-refuses to run without Alpaca paper credentials.

set -euo pipefail

LABEL="com.loaded.options-paper"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $PLIST and unloaded the agent."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd ${REPO}/backend &amp;&amp; set -a &amp;&amp; source ../.env &amp;&amp; set +a &amp;&amp; export OPT_END_PT=13:00 OPTIONS_REPORT_PATH=/tmp/spy_options_report.json PYTHONUNBUFFERED=1 &amp;&amp; exec ./.venv/bin/python -m app.options_paper_job</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>1</integer>
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>25</integer>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>/tmp/spy_options_job.log</string>
  <key>StandardErrorPath</key><string>/tmp/spy_options_job.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed + loaded: $PLIST"
echo "  fires:  Mondays 06:25 America/Los_Angeles (job trades 09:30 ET → 13:00 PT)"
echo "  report: /tmp/spy_options_report.json   log: /tmp/spy_options_job.log"
echo "  remove: ./scripts/install_options_paper_agent.sh --uninstall"
