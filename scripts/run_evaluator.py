#!/usr/bin/env python3
"""
Loaded — Project Evaluator Loop Runner

Runs the root-level project evaluator via Claude API, iterating until
the overall score reaches a target or max iterations are exhausted.

Usage:
  python scripts/run_evaluator.py                  # 3 iterations, target 9.0
  python scripts/run_evaluator.py --iterations 10
  python scripts/run_evaluator.py --until 9.0
  python scripts/run_evaluator.py --iterations 5 --until 8.5
  python scripts/run_evaluator.py --dry-run        # print prompt only, no API call
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

def collect_context() -> str:
    """Gather all codebase context to inject into the evaluator prompt."""
    sections = []

    sections.append("## CLAUDE.md\n" + load_file(ROOT / "CLAUDE.md"))
    sections.append("## ai/evaluator/project_evaluator.md\n" + load_file(ROOT / "ai/evaluator/project_evaluator.md"))

    # Generator prompts
    for f in sorted((ROOT / "ai/generator").rglob("*_generator.md")):
        rel = f.relative_to(ROOT)
        sections.append(f"## {rel}\n" + f.read_text())

    # Backend source
    for f in sorted((ROOT / "backend/app").rglob("*.py")):
        rel = f.relative_to(ROOT)
        sections.append(f"## {rel}\n```python\n{f.read_text()}\n```")

    # Tests
    for f in sorted((ROOT / "backend/tests").rglob("*.py")):
        rel = f.relative_to(ROOT)
        sections.append(f"## {rel}\n```python\n{f.read_text()}\n```")

    # Frontend pages + components
    for f in sorted((ROOT / "frontend/src").rglob("*.tsx")):
        rel = f.relative_to(ROOT)
        sections.append(f"## {rel}\n```tsx\n{f.read_text()}\n```")

    # Prior benchmark results
    results_dir = ROOT / "ai/benchmarks/results"
    if results_dir.exists():
        for f in sorted(results_dir.glob("*.json"))[-3:]:  # last 3 runs
            sections.append(f"## Prior benchmark: {f.name}\n```json\n{f.read_text()}\n```")

    return "\n\n---\n\n".join(sections)


def load_last_scores() -> dict:
    results_dir = ROOT / "ai/benchmarks/results"
    project_results = sorted(results_dir.glob("project_health_*.json")) if results_dir.exists() else []
    if not project_results:
        return {}
    try:
        return json.loads(project_results[-1].read_text()).get("scores", {})
    except Exception:
        return {}


def save_result(result: dict, iteration: int):
    results_dir = ROOT / "ai/benchmarks/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = results_dir / f"project_health_{date}_iter{iteration}.json"
    path.write_text(json.dumps(result, indent=2))
    print(f"  → Saved: {path.relative_to(ROOT)}")
    return path


def run_evaluation(iteration: int, last_scores: dict, dry_run: bool) -> dict | None:
    context = collect_context()

    prompt = f"""You are running iteration {iteration} of the Loaded project evaluator.

Follow the instructions in `ai/evaluator/project_evaluator.md` exactly.

Prior scores (for delta calculation):
{json.dumps(last_scores, indent=2) if last_scores else "No prior run — this is iteration 1."}

Here is the full codebase context:

{context}

---

Now run all 6 evaluation dimensions. Output the JSON block first, then the plain English summary table.
The JSON must be valid and parseable. Wrap it in ```json ... ``` fences.
"""

    if dry_run:
        print("=== DRY RUN — prompt only ===")
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

    print(f"\n  Calling Claude (iteration {iteration})...")
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    print("\n" + "="*60)
    print(raw)
    print("="*60 + "\n")

    # Extract JSON from fences
    result = None
    if "```json" in raw:
        try:
            json_str = raw.split("```json")[1].split("```")[0].strip()
            result = json.loads(json_str)
        except Exception as e:
            print(f"  Warning: could not parse JSON from response: {e}")

    if result is None:
        result = {
            "run": {"iteration": iteration, "date": datetime.now(timezone.utc).isoformat()},
            "scores": {},
            "raw_response": raw,
        }

    result["run"]["iteration"] = iteration
    return result


def main():
    parser = argparse.ArgumentParser(description="Run the Loaded project evaluator loop")
    parser.add_argument("--iterations", type=int, default=3, help="Max iterations (default: 3)")
    parser.add_argument("--until", type=float, default=9.0, help="Stop when overall score >= this (default: 9.0)")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt without calling API")
    args = parser.parse_args()

    # Load .env if present
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    print(f"\n🔍 Loaded Project Evaluator")
    print(f"   Max iterations : {args.iterations}")
    print(f"   Target score   : {args.until}/10")
    print(f"   Model          : claude-opus-4-5\n")

    last_scores = load_last_scores()

    for i in range(1, args.iterations + 1):
        print(f"{'─'*60}")
        print(f"  Iteration {i}/{args.iterations}")
        print(f"{'─'*60}")

        result = run_evaluation(i, last_scores, args.dry_run)

        if args.dry_run:
            break

        if result:
            save_result(result, i)
            overall = result.get("scores", {}).get("overall", 0)
            print(f"  Overall score: {overall}/10")

            if overall >= args.until:
                print(f"\n✅ Target score {args.until} reached at iteration {i}. Done.")
                break

            last_scores = result.get("scores", {})

            if i < args.iterations:
                next_action = result.get("next_action", "")
                if next_action:
                    print(f"\n  Next action: {next_action}\n")
                print(f"  Continuing to iteration {i+1}...\n")

    print("\nEvaluator loop complete.")


if __name__ == "__main__":
    main()
