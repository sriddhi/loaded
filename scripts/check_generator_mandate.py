#!/usr/bin/env python3
"""
Source-agnostic enforcement of CLAUDE.md Rule #1.

This is the REAL mandate: it runs in CI and in the pre-commit hook, so it
applies to code from ANY source — Claude, Cursor, Copilot, Aider, pasted from
a chat, or hand-typed. No AI instruction file can do that; only the git/CI
layer every change passes through can.

Two independent checks:

  1. LOCK INTEGRITY — every prompt listed in ai/locks/locked.json must still
     hash to its recorded sha256. A changed locked prompt without a matching
     unlock_log.json entry (with a reason) is a hard failure.

  2. MODULE COVERAGE — if a changed file falls under a module's code_globs
     (ai/mandate.json), that module must have at least one generator AND one
     evaluator prompt. Touching code with no generator+evaluator is a hard
     failure.

Usage:
    # Check a diff range (CI):
    python3 scripts/check_generator_mandate.py --base origin/main --head HEAD

    # Check staged files (pre-commit hook):
    python3 scripts/check_generator_mandate.py --staged

    # Check the whole tree (audit):
    python3 scripts/check_generator_mandate.py --all

Exit code 0 = pass, 1 = violation, 2 = usage/internal error.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANDATE_PATH = ROOT / "ai" / "mandate.json"
LOCKS_PATH = ROOT / "ai" / "locks" / "locked.json"
UNLOCK_LOG_PATH = ROOT / "ai" / "locks" / "unlock_log.json"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"{RED}git command failed: {' '.join(cmd)}{RESET}\n")
        sys.stderr.write(result.stderr)
        sys.exit(2)
    return result.stdout


def changed_files(args: argparse.Namespace) -> list[str]:
    if args.all:
        out = _run(["git", "ls-files"])
    elif args.staged:
        out = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    else:
        base = args.base or "origin/main"
        head = args.head or "HEAD"
        # Use merge-base so we only see what THIS branch changed.
        merge_base = _run(["git", "merge-base", base, head]).strip()
        out = _run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", merge_base, head]
        )
    return [line.strip() for line in out.splitlines() if line.strip()]


def matches_any(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def glob_has_match(globs: list[str]) -> bool:
    """True if at least one file on disk matches one of the globs."""
    for g in globs:
        if any(ROOT.glob(g)):
            return True
    return False


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_lock_integrity() -> list[str]:
    """Return list of violation messages (empty = pass)."""
    violations: list[str] = []
    if not LOCKS_PATH.exists():
        return violations
    locked = json.loads(LOCKS_PATH.read_text()).get("locked_files", [])

    unlocked_paths: set[str] = set()
    if UNLOCK_LOG_PATH.exists():
        try:
            log = json.loads(UNLOCK_LOG_PATH.read_text())
            if isinstance(log, list):
                entries = log
            else:
                # unlock_prompt.sh writes under "unlock_events"; accept "unlocks" too.
                entries = log.get("unlock_events", log.get("unlocks", []))
            unlocked_paths = {e.get("path") for e in entries if isinstance(e, dict)}
        except (json.JSONDecodeError, AttributeError):
            pass

    for entry in locked:
        rel = entry["path"]
        recorded = entry["sha256"]
        abs_path = ROOT / rel
        if not abs_path.exists():
            violations.append(f"locked prompt is missing from disk: {rel}")
            continue
        actual = sha256_of(abs_path)
        if actual != recorded:
            if rel in unlocked_paths:
                continue  # legitimately unlocked with a logged reason
            violations.append(
                f"locked prompt was modified without unlocking: {rel}\n"
                f"      recorded sha256: {recorded}\n"
                f"      actual   sha256: {actual}\n"
                f"      → run: ./scripts/unlock_prompt.sh {rel} \"<reason>\""
            )
    return violations


def check_module_coverage(files: list[str]) -> list[str]:
    """Return list of violation messages (empty = pass)."""
    mandate = json.loads(MANDATE_PATH.read_text())
    modules = mandate["modules"]
    exempt = mandate.get("exempt_globs", [])

    violations: list[str] = []
    touched_modules: dict[str, list[str]] = {}

    for f in files:
        if matches_any(f, exempt):
            continue
        for mod in modules:
            if matches_any(f, mod["code_globs"]):
                touched_modules.setdefault(mod["name"], []).append(f)
                break

    for mod in modules:
        name = mod["name"]
        if name not in touched_modules:
            continue
        has_gen = glob_has_match(mod["generator_globs"])
        has_eval = glob_has_match(mod["evaluator_globs"])
        if not (has_gen and has_eval):
            missing = []
            if not has_gen:
                missing.append(f"generator ({', '.join(mod['generator_globs'])})")
            if not has_eval:
                missing.append(f"evaluator ({', '.join(mod['evaluator_globs'])})")
            sample = ", ".join(touched_modules[name][:3])
            violations.append(
                f"module '{name}' was changed ({sample}) but is missing: "
                f"{' and '.join(missing)}"
            )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="check staged files")
    group.add_argument("--all", action="store_true", help="audit the whole tree")
    parser.add_argument("--base", help="base ref for diff (default origin/main)")
    parser.add_argument("--head", help="head ref for diff (default HEAD)")
    args = parser.parse_args()

    if not MANDATE_PATH.exists():
        sys.stderr.write(f"{RED}missing {MANDATE_PATH}{RESET}\n")
        return 2

    files = changed_files(args)

    print(f"{BOLD}Rule #1 mandate check{RESET} — {len(files)} changed file(s)")

    lock_violations = check_lock_integrity()
    coverage_violations = check_module_coverage(files)
    all_violations = lock_violations + coverage_violations

    if not all_violations:
        print(f"{GREEN}✓ lock integrity OK{RESET}")
        print(f"{GREEN}✓ generator+evaluator coverage OK{RESET}")
        print(f"{GREEN}{BOLD}PASS{RESET} — Rule #1 satisfied.")
        return 0

    if lock_violations:
        print(f"\n{RED}{BOLD}✗ LOCK INTEGRITY{RESET}")
        for v in lock_violations:
            print(f"  {RED}•{RESET} {v}")
    if coverage_violations:
        print(f"\n{RED}{BOLD}✗ GENERATOR + EVALUATOR COVERAGE{RESET}")
        for v in coverage_violations:
            print(f"  {RED}•{RESET} {v}")

    print(
        f"\n{YELLOW}Rule #1 (CLAUDE.md): no code without a locked generator + "
        f"evaluator.{RESET}"
    )
    print(
        f"{YELLOW}This gate is source-agnostic — it applies whether the code came "
        f"from Claude, Cursor, Copilot, or a human.{RESET}"
    )
    print(f"{RED}{BOLD}FAIL{RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
