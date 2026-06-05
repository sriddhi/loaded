# Locks

Lists all finalized generator and evaluator prompts that are locked from modification.

**Locked files cannot be edited during build or test phases.** The git pre-commit hook enforces this.

## How to Lock a File

Once a generator/evaluator is finalized and confirmed:

```bash
./scripts/lock_prompt.sh ai/generator/strategies/strategy_generator.md
./scripts/lock_prompt.sh ai/evaluator/strategies/strategy_evaluator.md
```

This adds the file path + SHA256 hash to `ai/locks/locked.json`.

## How to Unlock a File (deliberate, requires justification)

```bash
./scripts/unlock_prompt.sh ai/generator/strategies/strategy_generator.md "reason for unlock"
```

Unlocking removes the entry from `locked.json` and logs the action to `ai/locks/unlock_log.json`.

## Locked Files

See `locked.json`.
