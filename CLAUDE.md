# Forge — development notes

Forge is a Claude-Code-style AI coding agent harness built from scratch in Python on Gemini
(Gemini Enterprise Agent Platform, formerly Vertex AI). Private/session notes live in CLAUDE.local.md.

## Conventions
- Own agent loop (NOT SDK automatic function calling) — the loop in `forge/agent.py` is the core.
- One file per concept: `agent.py` loop, `llm.py` provider, `tools/` one tool per file + registry,
  `permissions.py`, `context.py` (compaction), `session.py`, `hooks.py`, `subagent.py`, `prompts.py`, `ui.py`, `cli.py`.
- Tools return strings and raise `ToolError` for expected failures; the agent never crashes on a tool error.
- Keep docs in `docs/` in sync with code when behavior changes.
- Install: `pip install -e .` -> `forge` command. Requires `FORGE_PROJECT` (or `GOOGLE_CLOUD_PROJECT`) env var.

## Milestones
1. [x] Core: REPL + loop + read/write/list/glob/grep tools
2. [x] edit_file + run_shell + permissions (ask/auto/readonly, y/n/always, blocklist)
3. [x] Memory (FORGE.md/AGENTS.md into system prompt) + sessions (.forge/sessions JSON, --resume)
4. [x] Context mgmt: tool-output truncation, token tracking, auto-compaction (checked every turn), /compact
5. [x] Extras: slash commands, `task` sub-agent, `todo` tool, hooks, headless `-p --json`, loop detection, read-before-edit guard
6. [x] Eval suite (`evals/`): 14 tasks + 12 hard tasks, `python evals/run.py` (first 7: 7/7 on 3.7-flash, $0.43)
7. [ ] SWE-bench Verified subset on a GCE VM (Docker) — scripts in swebench/, VM must be created by the user
8. [x] Docs (ARCHITECTURE, INTERVIEW, STUDY_GUIDE, DEMO, README); [x] pushed to GitHub (public)
9. [x] Offline test suite (tests/, ~190 tests, FakeLLM) + GitHub Actions CI (ubuntu+windows)
10. [x] Streaming (REPL), parallel read-only tool calls, MCP client (forge/mcp_client.py), skills + custom commands
11. [x] Checkpoints + /undo, web_fetch (SSRF guard), plan mode (/plan, exit_plan), code-review fixes (278 tests)
12. [ ] Final benchmark numbers: evals/RESULTS.md via `python evals/aggregate.py` after re-running infra errors
    (`python evals/run.py --resume evals/results/<file>.json`)

## Gemini facts (verified 2026-09-26)
- gemini-3.8-flash is on Dynamic Shared Quota and was overloaded (504 on every call).
  => `llm.py`: fallback chain (3.8 -> 3.7 -> 3.5 flash), timeouts/504 skip straight to next model,
  circuit breaker skips a failed model for 10 min. Evals use `--model gemini-3.7-flash --no-fallback`.
- Switching models mid-conversation (thought signatures in history) works — tested 3.7 -> 3.5 -> 3.1-pro -> 2.5.
- Thought signatures must be sent back: we append raw `resp.content` to history, which preserves them.
- Prices in `pricing.py`: 3.8/3.7-flash $0.75 in / $3.75 out per 1M (intro rate to 2026-12-31).
- Location `global`. `vertexai=True` works in google-genai 2.20.
