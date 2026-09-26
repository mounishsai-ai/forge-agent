Review the current change for correctness bugs, not style nits.

Steps:
1. Run `git status` and `git diff` (staged and unstaged) with run_shell to see what changed.
2. For each file touched, read enough surrounding context with read_file to judge correctness.
3. Report findings as a short list: file path, line reference, one sentence on why it's a bug.
4. If nothing significant is wrong, say so plainly — do not invent findings to fill space.

Focus area (optional, from the user — may be empty): $ARGUMENTS
