---
name: review-code
description: Review user-specified code, diffs, files, commits, or the last changes made by the agent when no target is specified. Use for code-review requests that should check Python code against the repository's .agents/rules/python.md and report bugs, regressions, style violations, missing tests, and maintainability risks before summaries.
---
<!-- vendored from workspace/.agents/skills/review-code/SKILL.md — do not edit; run `python scripts/sync.py agents` -->

# Review Code

## Workflow

1. Identify the review target from the user's request. If the user does not specify a target, review the last changes made by the agent in the current workspace.
2. Read the applicable repository instructions before reviewing. Always read `.agents/rules/python.md` when Python code is involved.
3. Inspect the target exactly. Prefer `git diff`, `git show`, and direct file reads over memory. For unstaged or mixed worktrees, distinguish user changes from agent changes when possible.
4. Review with a bug-finding stance. Prioritize behavioral regressions, incorrect typing, broken contracts, concurrency or async mistakes, bad error handling, missing validation, missing tests, and violations of `.agents/rules/python.md`.
5. Review from a system architecture perspective. Check that the code is modular, well-factored, elegant and easy to understand. There should be no hacks, "code smells", or other anti-patterns.
6. Report findings first, ordered by severity. Include clickable file references with exact line numbers when possible.
7. Keep summaries secondary. If no findings are found, say so clearly and mention residual risk or tests not run.

## Python Review Focus

1. Check that Python style follows `.agents/rules/python.md`, especially 2-space indentation, single quotes for normal strings, concise docstrings for modules/functions/classes, no `from __future__ import annotations`, and no unnecessary `__all__` in `__init__.py`.
2. Check type precision. Prefer `typing_extensions`, built-in collection generics, discriminated unions without redundant casts/asserts, `TypedDict`/`Literal` where appropriate, and keyword-only parameters when several parameters share the same type.
3. Check function signatures against local contracts. Do not accept broad optional parameters, loose dictionaries, or invalid parameter combinations when the spec can be represented precisely.
4. Check tests and validation. Flag missing or weak tests when the change touches shared behavior, public APIs, parsing, IO, async flows, or bug-prone edge cases.

## Output Format

1. Start with findings. Use numbered lists, not bullets, when enumerating findings.
2. For each finding, include severity, file and line, the concrete problem, and why it matters.
3. After findings, include open questions or assumptions only if they affect review confidence.
4. End with a brief summary or test note. Do not let the summary bury issues.
5. Avoid rewriting the code unless the user explicitly asks for fixes.
