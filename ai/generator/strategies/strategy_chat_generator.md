# Generator — `strategies` chat assistant (market agent + strategy builder)

**Module:** `strategies` (`backend/app/strategies/**`), endpoint `POST /strategies/chat`.

## Purpose
An agentic, market-aware chat assistant that powers the Strategy Lab's left
panel. It both answers market/data questions AND designs/edits `StrategyConfig`s.
Each turn returns a reply plus a typed **artifact** that drives the right panel.

**Read-only except for proposing configs. It never places trades and never
mutates the DB. Paper/indicator tool, not financial advice.**

## Decisions (fixed)
- Reuse the Anthropic pattern from `generator.py` (`claude-opus-4-5`). The
  blocking SDK runs via `asyncio.to_thread`.
- Ephemeral history: the client sends the full `messages` array each turn; the
  server is stateless (shaped so persistence can be added later).
- Tool use (Anthropic `tools=`), agentic loop: while `stop_reason == "tool_use"`,
  execute the requested tools, append `tool_result` blocks, re-call. Cap at ~5
  iterations to bound latency/cost.

## `chat.py`
- `async def chat(messages: list[dict]) -> dict` returning
  `{ "reply": str, "messages": [...], "artifact": {"type": ..., "data": ...} }`.
- Artifact `type` ∈ `strategy | market_data | backtest | text`.
- Tools (all read-only, reuse existing modules):
  - `get_most_active(by, top)` / `get_market_movers(top)` → `app/marketdata`.
  - `get_fundamentals(symbol)` → `app/agents`.
  - `get_quote(symbol)`.
  - `propose_strategy(config)` → validates against `StrategyConfig`; sets the
    artifact to `{type:"strategy", data:<config>}`.
- System prompt: a trading-strategy assistant; ask clarifying questions; when the
  user wants a strategy, call `propose_strategy` with a complete config; for
  market questions, call the data tools and summarize. No execution.
- If `ANTHROPIC_API_KEY` is missing → 503 with a clear message.

## Tests
- Mock Anthropic to force a `tool_use` → tool executes → final artifact typed
  correctly; market-data branch; strategy branch; missing-key path.
