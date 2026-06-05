#!/usr/bin/env bash
# Usage: ./scripts/lock_prompt.sh <file-path>
# Locks a generator or evaluator prompt file — blocks future git commits that modify it.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCKS_PATH="$ROOT/ai/locks/locked.json"

if [[ $# -lt 1 ]]; then
  echo "Usage: ./scripts/lock_prompt.sh <file-path>"
  echo "Example: ./scripts/lock_prompt.sh ai/generator/strategies/strategy_generator.md"
  exit 1
fi

FILE_PATH="$1"
ABS_PATH="$ROOT/$FILE_PATH"

if [[ ! -f "$ABS_PATH" ]]; then
  echo "❌ File not found: $FILE_PATH"
  exit 1
fi

# Compute SHA256
HASH=$(shasum -a 256 "$ABS_PATH" | awk '{print $1}')
LOCKED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Check if already locked
ALREADY=$(python3 -c "
import json
data = json.load(open('$LOCKS_PATH'))
paths = [e['path'] for e in data.get('locked_files', [])]
print('yes' if '$FILE_PATH' in paths else 'no')
")

if [[ "$ALREADY" == "yes" ]]; then
  echo "⚠️  Already locked: $FILE_PATH"
  exit 0
fi

# Add to locked.json
python3 -c "
import json
data = json.load(open('$LOCKS_PATH'))
data['locked_files'].append({
    'path': '$FILE_PATH',
    'sha256': '$HASH',
    'locked_at': '$LOCKED_AT',
    'version': '1.0'
})
with open('$LOCKS_PATH', 'w') as f:
    json.dump(data, f, indent=2)
print('ok')
"

echo "🔒 Locked: $FILE_PATH"
echo "   SHA256: $HASH"
echo "   At:     $LOCKED_AT"
echo ""
echo "   Commit ai/locks/locked.json to enforce the lock for all collaborators."
