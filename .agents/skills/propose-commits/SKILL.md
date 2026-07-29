---
name: propose-commits
description: Inspect a dirty git worktree and organize changes into sensible commit proposals. Use when the user asks Codex to propose commits, group changes by commit, organize progress into commits, identify which files to add for each commit, or commit only after explicit approval of a proposed grouping.
---
<!-- vendored from workspace/.agents/skills/propose-commits/SKILL.md — do not edit; run `python scripts/sync.py agents` -->

# Propose Commits

## Core Contract

Inspect the current git changes and propose a commit plan before committing.

Do not create commits during the proposal step. Only commit after the user explicitly approves a specific grouping or says to go ahead with the proposed commits.

Respect dirty worktrees. Never revert, discard, or stage unrelated changes. Treat untracked generated data, scratch workspaces, local notes, and user-designated ignored paths as out of scope unless the user explicitly asks to include them.

## Proposal Workflow

1. Identify the relevant repo root with `git rev-parse --show-toplevel`.
2. Inspect `git status --short`, `git diff --stat`, and enough focused diffs to understand the work.
3. Separate unrelated work by behavior, user-facing outcome, or implementation area.
4. For each proposed commit, output a title and exact files to stage.
5. Call out files intentionally excluded and why.
6. Stop and wait for user feedback or explicit approval.

Prefer explicit file lists over broad `git add .`. If a single file contains changes for multiple proposed commits, say that hunk staging is required and explain the split.

## Commit Workflow

After explicit approval:

1. Recheck `git status --short` before staging.
2. Stage only the approved paths, using explicit `git add <paths...>`.
3. Verify with `git diff --cached --name-only` or `git diff --cached --stat`.
4. Commit with the approved title.
5. Repeat one commit at a time.
6. Finish with `git log --oneline -n <count>` and `git status --short`.

If staging or committing fails because `.git` metadata is outside the sandbox writable root, request escalation for the exact git command. Do not work around git by copying files or mutating metadata manually.

## Proposal Format

Use concise sections:

**1. Commit Title**

Add: `git add path/a path/b`

Notes: mention hunk staging, exclusions, or coupling only when relevant.

Keep titles imperative or noun-phrase style, matching the repo's recent commit style. Avoid over-splitting tiny related changes; avoid bundling behaviorally unrelated changes just because they touched the same feature area.

## Exclusions

Do not include these unless explicitly requested:

- Build outputs, caches, virtualenvs, databases, and downloaded dependencies.
- Scratch or agent workspaces such as `.agents/workspaces/`, `.ref/`, or temporary directories.
- Local-only ignore files or notes unless the user asks to track them.
- Large raw data folders when the user says they should be ignored, even if they are not in `.gitignore`.
