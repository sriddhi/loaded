# Evaluator — `strategies` chat assistant

Score each ❌/✅. Fix all ❌ before done.

## Correctness
- [ ] `chat(messages)` returns `{reply, messages, artifact}` with artifact.type ∈
      `strategy|market_data|backtest|text`.
- [ ] Agentic loop runs tools while `stop_reason == "tool_use"`, appends
      `tool_result`, re-calls, and is capped (~5 iterations).
- [ ] `propose_strategy` validates against `StrategyConfig` and yields a
      `strategy` artifact; invalid config is reported, not crashed.
- [ ] Market tools reuse `marketdata`/`agents` (no reimplementation).
- [ ] Missing `ANTHROPIC_API_KEY` → 503 with a clear message.

## Safety
- [ ] No trade execution, no DB mutation in the chat path.
- [ ] `/strategies/chat` is under the JWT auth dependency.
- [ ] Labeled paper/indicator, not financial advice.

## Tests / quality
- [ ] Tool-use loop + artifact typing covered with a mocked Anthropic client.
- [ ] Blocking SDK call offloaded via `asyncio.to_thread`.
- [ ] Strict mypy + ruff clean.
