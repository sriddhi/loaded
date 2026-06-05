#!/usr/bin/env bash
# Usage: ./scripts/unlock_prompt.sh <file-path> "<reason>"
# Unlocks a prompt file and logs the action.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCKS_PATH="$ROOT/ai/locks/locked.json"
LOG_PATH="$ROOT/ai/locks/unlock_log.json"

if [[ $# -lt 2 ]]; then
  echo "Usage: ./scripts/unlock_prompt.sh <file-path> \"<reason>\""
  echo "Example: ./scripts/unlock_prompt.sh ai/generator/strategies/strategy_generator.md \"Adding missing edge case for empty signals\""
  exit 1
fi

FILE_PATH="$1"
REASON="$2"
UNLOCKED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
UNLOCKED_BY=$(git config user.name 2>/dev/null || echo "unknown")

# Remove from locked.json
REMOVED=$(python3 -c "
import json
data = json.load(open('$LOCKS_PATH'))
original = data['locked_files']
data['locked_files'] = [e for e in original if e['path'] != '$FILE_PATH']
removed = len(original) - len(data['locked_files'])
with open('$LOCKS_PATH', 'w') as f:
    json.dump(data, f, indent=2)
print(removed)
")

if [[ "$REMOVED" == "0" ]]; then
  echo "⚠️  Not found in locks: $FILE_PATH"
  exit 1
fi

# Log the unlock event
python3 -c "
import json
data = json.load(open('$LOG_PATH'))
data['unlock_events'].append({
    'path': '$FILE_PATH',
    'reason': '$REASON',
    'unlocked_by': '$UNLOCKED_BY',
    'unlocked_at': '$UNLOCKED_AT'
})
with open('$LOG_PATH', 'w') as f:
    json.dump(data, f, indent=2)
"

echo "🔓 Unlocked: $FILE_PATH"
echo "   Reason:  $REASON"
echo "   By:      $UNLOCKED_BY"
echo ""
echo "   Commit ai/locks/ to propagate the unlock."
