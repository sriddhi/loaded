# Evaluator — `portfolio` AI advisor commentary

Score each ❌/✅. All ❌ fixed before done.

- [ ] Context is 100% server-built (no user free-text path into the prompt);
      size-capped ~4KB; includes holdings/scores/performance/health/macro/
      earnings sections when available.
- [ ] Provider dispatch honors STRATEGY_CHAT_PROVIDER (claude_code → bridge,
      else Anthropic API); both mocked in tests; failures → 503, never cached.
- [ ] Daily cache in agent_models (agent_type portfolio_commentary, entity_key
      owner:pid, versioned): second same-day call returns cached=True without
      a provider call; force=true regenerates and bumps version.
- [ ] Disclaimer line guaranteed in output (appended server-side if missing);
      system prompt forbids trade instructions/price targets.
- [ ] Endpoints owner-scoped (404), JWT'd; GET returns 404 before first
      generation.
- [ ] CommentaryCard renders markdown, cached badge, regenerate (force),
      loading + unavailable states.
- [ ] ruff + strict mypy clean; tests per app file; no real network in tests.
