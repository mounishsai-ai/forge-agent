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
        before = agent.history
        pending = before[-1] if before else None
        compact(agent)
        # This runs at the top of a turn, so the last message is what the model must answer NEXT
        # (the user's request or tool results). After compaction the history must still end with
        # a user message, or the model would be asked to reply to its own "Got it".
        if agent.history is not before and pending is not None and pending.role == "user":
            if pending.parts and all(p.text is not None for p in pending.parts):
                agent.history.append(pending)            # the user's request, verbatim
            else:   # tool results can't be re-sent without the calls they answer
                agent.history.append(types.Content(role="user", parts=[types.Part(
                    text="Continue the task from where you left off (see the summary above).")]))


def compact(agent) -> str:
    if len(agent.history) < 2:
        return "Nothing to compact."
    request = list(agent.history)
    last = request[-1]
    ask = types.Part(text=SUMMARY_PROMPT)
    if last.role == "user":
        # Merge into the last user message (e.g. tool results) instead of adding a 2nd user turn.
        request[-1] = types.Content(role="user", parts=[*(last.parts or []), ask])
    else:
        calls = [p.function_call for p in last.parts or [] if p.function_call]
        # A model turn whose tool calls never got results (the run died mid-turn): the API
        # rejects that, so answer each call before asking for the summary.
        request.append(types.Content(role="user", parts=[
            *[types.Part(function_response=types.FunctionResponse(
                id=c.id, name=c.name, response={"error": "Not run."})) for c in calls],
            ask]))
    with agent.ui.thinking():
        resp = agent.llm.generate(request, tools=[], system=agent.system_prompt)
    agent.usage.add(resp.usage)
    if not resp.text.strip() or resp.text.startswith("(empty response"):
        # Blocked / empty reply: replacing the history with it would lose the whole conversation.
        return "Compaction failed (the model returned no summary); history left unchanged."
    before = len(agent.history)
    agent.history = [
        types.Content(role="user", parts=[types.Part(text=f"[Summary of our earlier conversation]\n{resp.text}")]),
        types.Content(role="model", parts=[types.Part(text="Got it. I'll continue from this summary.")]),
    ]
    agent.last_prompt_tokens = 0
    return f"Compacted {before} messages into a summary ({resp.usage.output_tokens} tokens)."
