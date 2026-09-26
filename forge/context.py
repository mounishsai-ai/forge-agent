"""Context-window management.

Every turn re-sends the WHOLE history to the model, so cost and latency grow with it,
and eventually it won't fit. Three defenses:
  1. Tool outputs are truncated at the source (tools/base.py: truncate).
  2. Auto-compaction: once the prompt passes COMPACT_AT_TOKENS, the model summarizes the
     conversation and the history is replaced by that summary.
  3. The user can force it with /compact or wipe it with /clear.
"""
from google.genai import types

from forge import config

SUMMARY_PROMPT = """Summarize this conversation so work can continue in a fresh context. Include:
1. The user's goals and any explicit instructions/preferences.
2. What has been done so far: files read, created or changed (with paths) and key decisions.
3. Important facts discovered about the codebase (structure, commands, gotchas).
4. Errors hit and how they were resolved.
5. Current state and the exact next steps remaining.
Be specific and dense. Use file paths and names, not vague descriptions."""


def maybe_compact(agent) -> None:
    if agent.last_prompt_tokens > config.COMPACT_AT_TOKENS:
        agent.ui.info(f"Context at {agent.last_prompt_tokens:,} tokens; compacting...")
        compact(agent)


def compact(agent) -> str:
    if len(agent.history) < 2:
        return "Nothing to compact."
    request = agent.history + [types.Content(role="user", parts=[types.Part(text=SUMMARY_PROMPT)])]
    with agent.ui.thinking():
        resp = agent.llm.generate(request, tools=[], system=agent.system_prompt)
    agent.usage.add(resp.usage)
    before = len(agent.history)
    agent.history = [
        types.Content(role="user", parts=[types.Part(text=f"[Summary of our earlier conversation]\n{resp.text}")]),
        types.Content(role="model", parts=[types.Part(text="Got it. I'll continue from this summary.")]),
    ]
    agent.last_prompt_tokens = 0
    return f"Compacted {before} messages into a summary ({resp.usage.output_tokens} tokens)."
