---
name: git-commit
description: Commit message style for this repo — load before running git commit.
---

# Commit message style

- Subject line: imperative mood, no trailing period, under ~70 characters
  ("Add retry backoff to llm.py", not "Added retry backoff" or "Adds retry backoff").
- Explain WHY in the body when it isn't obvious from the diff alone — the reasoning or bug
  being fixed, not a line-by-line restatement of what changed.
- One logical change per commit. Don't bundle an unrelated fix into a feature commit.
- Never commit secrets, credentials, or `.env` files. Read `git status` and `git diff` for
  what's about to be staged before running `git add`.
- Stage specific files by name (`git add path/to/file.py`); avoid `git add -A` / `git add .`
  so nothing untracked gets swept in by accident.
- Only make a commit when the user has explicitly asked for one in this conversation.
