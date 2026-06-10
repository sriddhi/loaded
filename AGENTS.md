# AGENTS.md — Rules for ANY AI coding tool in this repo

> This file is the cross-tool standard read by Cursor, Aider, Windsurf, Zed,
> GitHub Copilot Workspace, and others. **Claude reads `CLAUDE.md`** (the full
> source of truth). Both point at the same non-negotiable mandate below.

## Rule #1 — Generator & Evaluator System (NON-NEGOTIABLE)

**Every piece of code built in this repo follows this system, regardless of
which tool or human wrote it.** Code from Claude, Cursor, Copilot, Aider, a
pasted ChatGPT snippet, or hand-typed by a human is held to the same standard.

Before writing or modifying code under `backend/app/{module}/`:

1. Finalize the design in conversation — no code yet.
2. Write `ai/generator/{module}/{feature}_generator.md` — the build spec.
3. Write `ai/evaluator/{module}/{feature}_evaluator.md` — the verification checklist.
4. Confirm + lock both: `./scripts/lock_prompt.sh <file>`
5. Build using the generator as the only spec.
6. Run the evaluator against the built code; fix all ❌ before done.

### This is enforced — not advisory

The mandate is not honor-system. It runs at the git/CI layer that **every**
change passes through, so it applies no matter what produced the code:

- **Pre-commit hook** (`.githooks/pre-commit`) — blocks commits that modify a
  locked prompt or touch a module with no generator+evaluator.
- **CI gate** (`.github/workflows/pr_checks.yml` → `rule1-mandate`) — **hard
  blocks merge** on the same rules. Cannot be bypassed.
- **Enforcement logic**: `scripts/check_generator_mandate.py`
  (config: `ai/mandate.json`).

To change a locked prompt: `./scripts/unlock_prompt.sh <file> "<reason>"` —
the reason is logged permanently in `ai/locks/unlock_log.json`.

### What never changes
- No code without a locked generator + evaluator.
- Locked prompts are immutable during build/test.
- Benchmark results are never deleted.

See `CLAUDE.md` and `ai/README.md` for the full reference.
