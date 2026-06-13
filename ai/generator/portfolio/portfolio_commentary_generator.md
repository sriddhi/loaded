# Generator — `portfolio` module, AI advisor commentary

A daily, cached, LLM-written portfolio review built from server-side context
only. Educational tone, hard guardrails, provider plumbing reused from the
strategies chat.

## commentary.py

- `build_context(pool, request deps, pid) -> dict` — compact JSON (≤ ~4KB):
  portfolio name/kind/value/cash, top holdings (symbol, weight, unrealized %,
  candidate + composite from latest scores), performance summary (twr_pct,
  simple_return_pct, beta), health (diversification score + non-ok checks),
  fired macro alerts (id, meaning), upcoming earnings ≤ 14d. Server-built only
  — no user free-text ever enters the prompt (prompt-injection-safe).
- `SYSTEM_PROMPT` (module constant): "You are an educational portfolio review
  assistant… markdown, ≤ ~400 words, plain language for a young retail
  audience, explain WHY using the provided context only, no trade
  instructions, no price targets, end with the exact disclaimer line." The
  disclaimer is ALSO appended server-side if the model omits it.
- Provider dispatch mirroring strategies chat env contract:
  - `STRATEGY_CHAT_PROVIDER=claude_code` → reuse
    `app.strategies.chat._bridge_chat(system, prompt)` (typed local at the
    boundary).
  - otherwise → direct `anthropic.Anthropic().messages.create` (no tools,
    max_tokens ~900, model = strategies chat MODEL).
- Caching in `agent_models`: agent_type 'portfolio_commentary', entity_key
  f"{owner_id}:{pid}", version = previous+1; analysis = {"markdown": …},
  supporting_data = context, data_as_of = now. `get_cached(pool, owner_id,
  pid)` returns today's latest version or None.
- `generate(pool, deps, owner_id, pid, force=False) -> {markdown, generated_at,
  cached, version}`: cache hit (same UTC day) unless force; on provider failure
  raise a typed error the router maps to 503 (never cache failures).

## Router additions

- GET `/portfolio/{pid}/commentary` → cached today's commentary or 404
  {detail: "no commentary yet"}.
- POST `/portfolio/{pid}/commentary` {force?: bool} → generate (cached unless
  force), returns {portfolio_id, markdown, generated_at, cached, version,
  disclaimer}; 503 on provider failure.
Owner-scoped 404s; JWT'd.

## UI — CommentaryCard on the /portfolio/[id] Insights tab

"AI advisor review" card: render markdown (simple paragraph/bold/list support
is enough — no new deps), generated_at + "cached" badge, "Regenerate" button
(force), loading and provider-unavailable states. Labeled educational.

## Tests (test_portfolio_commentary.py)

Same-day cache hit (second call cached=True, no provider call); force
regenerates (version bumps); provider dispatch mocked for both modes;
disclaimer appended when model omits it; context size cap enforced; provider
failure → 503 and nothing cached; owner scoping.

## Conventions

No user text in prompts; cents/dollars at boundaries; typed locals at
cross-module imports; ruff + strict mypy; Python 3.11-safe.
