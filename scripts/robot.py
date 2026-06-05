#!/usr/bin/env python3
"""
Loaded — Robot

Runs the project evaluator in a loop, scoring and improving either the
full project or a specific module, until a target score is reached or
max iterations are exhausted.

Usage:
  python scripts/robot.py                              # full project, 3 iterations, target 9.0
  python scripts/robot.py --module strategies          # only the strategies module
  python scripts/robot.py --module strategies --until 9.5
  python scripts/robot.py --iterations 10 --until 9.0
  python scripts/robot.py --dry-run                    # print prompt only, no API call

Available modules (mirrors ai/generator/ folders):
  strategies, market_data, portfolio, alerts, auth, ...
  Use --list-modules to see what exists in the current project.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent


def load_file(path: Path) -> str:
    try:
        return path.read_text()
    except Exception:
        return f"[could not read {path}]"


def list_modules() -> list[str]:
    """Return all modules that have a generator prompt."""
    gen_dir = ROOT / "ai/generator"
    if not gen_dir.exists():
        return []
    return sorted(set(f.parent.name for f in gen_dir.rglob("*_generator.md")))


def collect_context(module: str | None) -> str:
    """
    Gather codebase context.
    If module is set, only include files relevant to that module.
    Always includes CLAUDE.md and the evaluator prompt.
    """
    sections = []
    sections.append("## CLAUDE.md\n" + load_file(ROOT / "CLAUDE.md"))

    # Evaluator prompt — module-specific or project-level
    if module:
        module_eval = ROOT / f"ai/evaluator/{module}"
        eval_files = sorted(module_eval.glob("*_evaluator.md")) if module_eval.exists() else []
        if eval_files:
            for f in eval_files:
                sections.append(f"## {f.relative_to(ROOT)}\n" + f.read_text())
        else:
            # Fall back to project evaluator scoped to this module
            sections.append("## ai/evaluator/project_evaluator.md\n" + load_file(ROOT / "ai/evaluator/project_evaluator.md"))
            sections.append(f"## Scope restriction\nEvaluate ONLY the `{module}` module. Ignore all other modules.")
    else:
        sections.append("## ai/evaluator/project_evaluator.md\n" + load_file(ROOT / "ai/evaluator/project_evaluator.md"))

    # Generator prompts — scoped or all
    gen_dir = ROOT / "ai/generator"
    if module:
        gen_files = sorted((gen_dir / module).rglob("*_generator.md")) if (gen_dir / module).exists() else []
    else:
        gen_files = sorted(gen_dir.rglob("*_generator.md"))
    for f in gen_files:
        sections.append(f"## {f.relative_to(ROOT)}\n" + f.read_text())

    # Backend source — scoped or all
    backend_app = ROOT / "backend/app"
    if module:
        src_dirs = [backend_app / module] if (backend_app / module).exists() else []
        # Also include main.py for context
        main_py = backend_app / "main.py"
        if main_py.exists():
            sections.append(f"## backend/app/main.py\n```python\n{main_py.read_text()}\n```")
    else:
        src_dirs = [backend_app]
    for src_dir in src_dirs:
        for f in sorted(src_dir.rglob("*.py")):
            rel = f.relative_to(ROOT)
            sections.append(f"## {rel}\n```python\n{f.read_text()}\n```")

    # Tests — scoped or all
    tests_dir = ROOT / "backend/tests"
    if tests_dir.exists():
        test_pattern = f"*{module}*" if module else "*.py"
        for f in sorted(tests_dir.glob(test_pattern)):
            rel = f.relative_to(ROOT)
            sections.append(f"## {rel}\n```python\n{f.read_text()}\n```")

    # Frontend — scoped or all
    frontend_src = ROOT / "frontend/src"
    if module:
        fe_dirs = []
        for candidate in [
            frontend_src / "app" / module,
            frontend_src / "components" / module,
        ]:
            if candidate.exists():
                fe_dirs.append(candidate)
    else:
        fe_dirs = [frontend_src]
    for fe_dir in fe_dirs:
        for f in sorted(fe_dir.rglob("*.tsx")):
            rel = f.relative_to(ROOT)
            sections.append(f"## {rel}\n```tsx\n{f.read_text()}\n```")

    # Prior benchmark results — scoped or all (last 3)
    results_dir = ROOT / "ai/benchmarks/results"
    if results_dir.exists():
        prefix = f"{module}_" if module else "project_health_"
        prior = sorted(results_dir.glob(f"{prefix}*.json"))[-3:]
        for f in prior:
            sections.append(f"## Prior benchmark: {f.name}\n```json\n{f.read_text()}\n```")

    return "\n\n---\n\n".join(sections)


def load_last_scores(module: str | None) -> dict:
    """Load scores from the most recent run with the same scope."""
    results_dir = ROOT / "ai/benchmarks/results"
    if not results_dir.exists():
        return {}
    prefix = f"{module}_" if module else "project_health_"
    prior = sorted(results_dir.glob(f"{prefix}*.json"))
    if not prior:
        return {}
    try:
        return json.loads(prior[-1].read_text()).get("scores", {})
    except Exception:
        return {}


def print_summary(result: dict, iteration: int, scope_label: str):
    """Print a formatted summary table from the result."""
    scores = result.get("scores", {})
    overall = scores.get("overall", 0)
    delta = result.get("delta_from_last_run", {}).get("overall", 0)
    delta_str = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"

    print(f"\n  Overall: {overall}/10  △ {delta_str}")

    dims = scores.get("dimensions", {})
    if dims:
        print(f"\n  {'Dimension':<28} {'Score':>6}  {'Delta':>6}")
        print(f"  {'─'*28} {'─'*6}  {'─'*6}")
        dim_deltas = result.get("delta_from_last_run", {}).get("dimensions", {})
        for k, v in dims.items():
            d = dim_deltas.get(k, 0)
            d_str = f"+{d:.1f}" if d > 0 else f"{d:.1f}"
            print(f"  {k.replace('_',' ').title():<28} {v:>5.1f}   {d_str:>6}")

    modules = scores.get("modules", {})
    if modules:
        print(f"\n  {'Module':<16} {'Overall':>7}  {'Complete':>8}  {'Tests':>6}  {'Guard':>6}  {'Code':>6}")
        print(f"  {'─'*16} {'─'*7}  {'─'*8}  {'─'*6}  {'─'*6}  {'─'*6}")
        mod_deltas = result.get("delta_from_last_run", {}).get("modules", {})
        for mod, mv in modules.items():
            d = mod_deltas.get(mod, {}).get("overall", 0)
            d_str = f"△{d:+.1f}" if d != 0 else "     "
            print(f"  {mod:<16} {mv.get('overall',0):>5.1f}{d_str:>4}  "
                  f"{mv.get('completeness',0):>7.1f}  "
                  f"{mv.get('test_coverage',0):>5.1f}  "
                  f"{mv.get('guardrails',0):>5.1f}  "
                  f"{mv.get('code_quality',0):>5.1f}")

    next_action = result.get("next_action", "")
    if next_action:
        print(f"\n  ⚡ Next action: {next_action}")


def save_result(result: dict, iteration: int, module: str | None):
    results_dir = ROOT / "ai/benchmarks/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = f"{module}_" if module else "project_health_"
    path = results_dir / f"{prefix}{date}_iter{iteration}.json"
    path.write_text(json.dumps(result, indent=2))
    print(f"  → Saved: {path.relative_to(ROOT)}")
    return path


def run_evaluation(iteration: int, last_scores: dict, module: str | None, dry_run: bool) -> dict | None:
    context = collect_context(module)
    scope_label = f"the `{module}` module" if module else "the full project"

    prompt = f"""You are running iteration {iteration} of the Loaded robot evaluator.

Scope: {scope_label}

{"Follow the instructions in the module evaluator prompt above." if module else "Follow the instructions in `ai/evaluator/project_evaluator.md` exactly."}

Prior scores for {scope_label} (for delta calculation):
{json.dumps(last_scores, indent=2) if last_scores else "No prior run — this is iteration 1."}

Here is the codebase context for {scope_label}:

{context}

---

Run all evaluation dimensions relevant to {scope_label}.
Output the JSON block first (wrapped in ```json ... ``` fences), then the plain English summary table.
The JSON must be valid and parseable.
"""

    if dry_run:
        print(f"=== DRY RUN — scope: {scope_label} ===")
        print(prompt[:3000], "\n... [truncated]")
        return None

    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed. Run: pip install anthropic")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print(f"\n  Calling Claude (iteration {iteration}, scope: {scope_label})...")
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    print("\n" + "=" * 60)
    print(raw)
    print("=" * 60 + "\n")

    result = None
    if "```json" in raw:
        try:
            json_str = raw.split("```json")[1].split("```")[0].strip()
            result = json.loads(json_str)
        except Exception as e:
            print(f"  Warning: could not parse JSON from response: {e}")

    if result is None:
        result = {
            "run": {"iteration": iteration, "date": datetime.now(timezone.utc).isoformat(), "scope": module or "full"},
            "scores": {},
            "raw_response": raw,
        }

    result.setdefault("run", {})
    result["run"]["iteration"] = iteration
    result["run"]["scope"] = module or "full"
    return result


def main():
    parser = argparse.ArgumentParser(description="Loaded robot — project evaluator loop")
    parser.add_argument("--module", type=str, default=None,
                        help="Evaluate only this module (e.g. strategies). Omit for full project.")
    parser.add_argument("--iterations", type=int, default=3,
                        help="Max iterations (default: 3)")
    parser.add_argument("--until", type=float, default=9.0,
                        help="Stop when overall score >= this (default: 9.0)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompt without calling API")
    parser.add_argument("--list-modules", action="store_true",
                        help="List available modules and exit")
    args = parser.parse_args()

    if args.list_modules:
        modules = list_modules()
        if modules:
            print("Available modules:")
            for m in modules:
                print(f"  {m}")
        else:
            print("No modules found in ai/generator/")
        sys.exit(0)

    # Load .env
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    scope_label = f"module: {args.module}" if args.module else "full project"
    print(f"\n🤖 Loaded Robot")
    print(f"   Scope          : {scope_label}")
    print(f"   Max iterations : {args.iterations}")
    print(f"   Target score   : {args.until}/10")
    print(f"   Model          : claude-opus-4-5\n")

    last_scores = load_last_scores(args.module)

    for i in range(1, args.iterations + 1):
        print(f"{'─' * 60}")
        print(f"  Iteration {i}/{args.iterations}  [{scope_label}]")
        print(f"{'─' * 60}")

        result = run_evaluation(i, last_scores, args.module, args.dry_run)

        if args.dry_run:
            break

        if result:
            save_result(result, i, args.module)
            print_summary(result, i, scope_label)
            overall = result.get("scores", {}).get("overall", 0)

            if overall >= args.until:
                print(f"\n✅ Target {args.until} reached at iteration {i}. Done.")
                break

            last_scores = result.get("scores", {})

            if i < args.iterations:
                print(f"\n  Continuing to iteration {i + 1}...\n")

    print("\n🤖 Robot complete.")


if __name__ == "__main__":
    main()
