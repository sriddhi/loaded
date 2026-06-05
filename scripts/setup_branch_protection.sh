#!/usr/bin/env bash
# Loaded — Branch Protection Setup
# Sets GitHub branch protection: no merge to main/develop without passing CI.
# Run once after repo setup: ./scripts/setup_branch_protection.sh

set -euo pipefail

if ! command -v gh &>/dev/null; then
  echo "❌ gh CLI not found. Install: brew install gh"
  exit 1
fi

if ! gh auth status &>/dev/null 2>&1; then
  echo "❌ Not authenticated. Run: gh auth login"
  exit 1
fi

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo "Setting branch protection on: $REPO"

for BRANCH in main develop; do
  # Check branch exists on remote
  if ! gh api "repos/$REPO/branches/$BRANCH" &>/dev/null 2>&1; then
    echo "⚠️  Branch '$BRANCH' not found on remote — skipping"
    continue
  fi

  echo "  Protecting: $BRANCH"
  gh api \
    --method PUT \
    "repos/$REPO/branches/$BRANCH/protection" \
    --input - <<EOF
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["backend-quality", "frontend-quality"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false
}
EOF
  echo "  ✅ $BRANCH protected"
done

echo ""
echo "🔒 Branch protection active:"
echo "   - PRs to main/develop require: backend-quality ✓  frontend-quality ✓"
echo "   - Both CI jobs must pass — no exceptions, including admins"
echo "   - Force pushes blocked"
echo "   - Direct commits to main/develop blocked — PRs only"
