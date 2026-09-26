"""Entry point: parses flags, wires the pieces together, runs the REPL or a one-shot prompt.

    forge                      interactive chat
    forge -p "fix the bug"     one-shot (headless); prints the final answer
    forge --resume             continue the last saved session
    forge --yes                auto-approve writes/shell (careful)
"""
import argparse
import json
import os
import sys
import time

from google.genai import types

from forge import __version__, checkpoints, config, context, mcp_client, session, skills
from forge.agent import Agent
from forge.hooks import Hooks
from forge.llm import GeminiLLM
from forge.permissions import Permissions
from forge.prompts import build_system_prompt
from forge.subagent import make_task_tool
from forge.tools import ALL_TOOLS, base, exit_plan, todo
from forge.ui import ConsoleUI, QuietUI, console

HELP = """Commands:
  /help            this help
  /clear           start a fresh conversation
  /compact         summarize the conversation to free up context
  /undo [N]        revert file changes from the last N turns (default 1)
  /checkpoints     list turns that changed files
  /cost            tokens used and estimated cost
  /model [name]    show or switch model
  /tools           list tools
  /todo            show the current task list
  /mode [ask|auto|readonly]  show or change permission mode
  /plan            toggle plan mode (read-only exploration; model proposes a plan for approval)
  /sessions        list saved sessions
  /mcp             list MCP servers and their tools
  /exit            quit (session is auto-saved)"""


def build_agent(args, ui) -> Agent:
    llm = GeminiLLM(model=args.model, fallbacks=[] if args.no_fallback else config.FALLBACK_MODELS)
    mode = "auto" if args.yes else args.mode
    agent = Agent(llm=llm, ui=ui, permissions=Permissions(mode), system_prompt=build_system_prompt(),
                  tools=ALL_TOOLS, max_turns=args.max_turns, hooks=Hooks.load())
    if not args.no_subagents:
        task_tool = make_task_tool(agent)
        agent.tools[task_tool.name] = task_tool
    # exit_plan is registered unconditionally (like `task` above), not only under --plan: /plan can
    # switch plan mode on mid-session, and the tool needs to already exist for the model to call.
    plan_tool = exit_plan.make_exit_plan_tool(agent)
    agent.tools[plan_tool.name] = plan_tool
    if getattr(args, "plan", False):
        exit_plan.enter_plan_mode(agent)
    mcp_client.attach(agent)   # tools from .forge/mcp.json servers (mcp__<server>__<tool>)
    if getattr(args, "tools", None):
        # Restrict the toolset (used for ablation studies, e.g. --tools run_shell = "bash-only agent").
        keep = {t.strip() for t in args.tools.split(",") if t.strip()}
        agent.tools = {name: t for name, t in agent.tools.items() if name in keep}
    return agent


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge", description="Forge: an AI coding agent in your terminal.")
    p.add_argument("-p", "--prompt", help="run one prompt headlessly and exit")
    p.add_argument("--model", default=config.MODEL)
    p.add_argument("--mode", default="ask", choices=["ask", "auto", "readonly"])
    p.add_argument("-y", "--yes", action="store_true", help="auto-approve all tool calls (mode=auto)")
    p.add_argument("--resume", nargs="?", const="__last__", help="resume a session (default: most recent)")
    p.add_argument("--max-turns", type=int, default=config.MAX_TURNS)
    p.add_argument("--json", action="store_true", help="with -p: print a JSON result (for scripts/evals)")
    p.add_argument("--verbose", action="store_true", help="with -p: show tool calls")
    p.add_argument("--no-subagents", action="store_true")
    p.add_argument("--tools", help="comma-separated tool names to keep (others are removed), e.g. run_shell")
    p.add_argument("--no-fallback", action="store_true", help="never switch models (for reproducible evals)")
    p.add_argument("--plan", action="store_true",
                    help="start in plan mode: read-only until the model's plan is approved (see /plan)")
    p.add_argument("--version", action="version", version=f"forge {__version__}")
    return p


def main() -> None:
    args = build_parser().parse_args()

    if args.prompt:
        sys.exit(run_headless(args))
    repl(args)


def run_headless(args) -> int:
    ui = QuietUI(verbose=args.verbose)
    agent = build_agent(args, ui)
    start = time.time()
    try:
        result = agent.run(args.prompt)
        error = None
    except Exception as e:
        result, error = "", f"{type(e).__name__}: {e}"
    if args.json:
        print(json.dumps({
            "result": result, "error": error, "model": agent.llm.model,
            "seconds": round(time.time() - start, 1), "tool_calls": agent.tool_calls_made,
            "input_tokens": agent.usage.input_tokens, "output_tokens": agent.usage.output_tokens,
            "thinking_tokens": agent.usage.thinking_tokens,
            "cost_usd": round(agent.usage.cost_usd, 6), "model_used": agent.llm.last_model_used,
        }))
    else:
        print(error or result)
    return 1 if error else 0


def repl(args) -> None:
    ui = ConsoleUI()
    agent = build_agent(args, ui)
    sid = session.new_session_id()
    if args.resume:
        try:
            sid, agent.history = session.load(None if args.resume == "__last__" else args.resume)
            ui.info(f"Resumed session {sid} ({len(agent.history)} messages).")
        except FileNotFoundError as e:
            ui.error(str(e))
        except Exception as e:   # corrupt / hand-edited session file: start fresh instead of crashing
            ui.error(f"Could not load session ({type(e).__name__}: {e}). Starting a new one.")
    checkpoints.set_session(sid)   # on --resume this reloads saved checkpoints, so /undo still works

    mode_label = f"{agent.permissions.mode} (plan)" if agent.permissions.plan_mode else agent.permissions.mode
    console.print(f"[bold]Forge[/] v{__version__}  [dim]{agent.llm.model} | mode: {mode_label} | "
                  f"{os.getcwd()}[/]\n[dim]Type /help for commands. Ctrl+C interrupts, /exit quits.[/]")
    while True:
        try:
            text = console.input("\n[bold green]> [/]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.startswith("/"):
            if handle_command(text, agent, ui) == "exit":
                break
            continue
        try:
            checkpoints.begin_turn(text)   # new user turn = new checkpoint group (agent.py stays unaware)
            agent.run(text)
        except Exception as e:   # API errors etc: report and keep the session alive
            ui.error(f"{type(e).__name__}: {e}")
        session.save(sid, agent)
    session.save(sid, agent)
    ui.info(f"Session saved: {sid}  (resume with: forge --resume {sid})")


def handle_command(text: str, agent: Agent, ui) -> str | None:
    cmd, _, arg = text.partition(" ")
    arg = arg.strip()
    if cmd in ("/exit", "/quit"):
        return "exit"
    elif cmd == "/help":
        console.print(HELP)
        custom = skills.discover_commands()
        if custom:
            console.print("\nCustom commands (.forge/commands/*.md):")
            for name in sorted(custom):
                console.print(f"  /{name}")
    elif cmd == "/clear":
        agent.history.clear()
        agent.last_prompt_tokens = 0
        ui.info("Conversation cleared.")
    elif cmd == "/compact":
        ui.info(context.compact(agent))
    elif cmd == "/cost":
        u = agent.usage
        ui.info(f"input {u.input_tokens:,} | output {u.output_tokens:,} | thinking {u.thinking_tokens:,} | "
                f"cached {u.cached_tokens:,} | context now {agent.last_prompt_tokens:,} | "
                f"est. cost ${u.cost_usd:.4f}")
    elif cmd == "/model":
        if arg:
            agent.llm.model = arg
        ui.info(f"Model: {agent.llm.model}")
    elif cmd == "/tools":
        for t in agent.tools.values():
            console.print(f"  [cyan]{t.name}[/]{' [yellow](asks)[/]' if t.needs_permission else ''} - "
                          f"{t.description.split('.')[0]}")
    elif cmd == "/todo":
        console.print(todo.render())
    elif cmd == "/mode":
        if agent.permissions.plan_mode:
            ui.error("In plan mode: use /plan to exit before changing the permission mode.")
        else:
            if arg in ("ask", "auto", "readonly"):
                agent.permissions.mode = arg
            ui.info(f"Permission mode: {agent.permissions.mode}")
    elif cmd == "/plan":
        if agent.permissions.plan_mode:
            exit_plan.leave_plan_mode(agent)
            ui.info(f"Plan mode off. Permission mode: {agent.permissions.mode}")
        else:
            exit_plan.enter_plan_mode(agent)
            ui.info("Plan mode on: read-only until the model proposes a plan and you approve it.")
    elif cmd == "/sessions":
        ui.info("\n".join(session.list_sessions()) or "No sessions.")
    elif cmd == "/undo":
        undo_turns(arg, agent, ui)
    elif cmd == "/checkpoints":
        turns = checkpoints.list_turns()
        if not turns:
            ui.info("No checkpoints yet (no files changed by write_file/edit_file).")
        for back, t in enumerate(reversed(turns), 1):   # numbered like /undo N: 1 = most recent
            console.print(f"  {back}  {t['time']}  {t['prompt'][:60]!r}  "
                          f"({len(t['files'])} file(s): {', '.join(os.path.basename(f) for f in t['files'])})",
                          highlight=False, markup=False)   # prompt text may contain [brackets]
    elif cmd == "/mcp":
        console.print(mcp_client.status(), highlight=False, markup=False)
    else:
        # Not a built-in: check .forge/commands/<name>.md before giving up. Built-ins above
        # always win on a name clash since they're checked first in this elif chain.
        custom = skills.discover_commands()
        name = cmd[1:]
        if name in custom:
            try:
                checkpoints.begin_turn(text)
                agent.run(skills.render_command(custom[name], arg))
            except Exception as e:   # same handling as a plain-text turn in repl()
                ui.error(f"{type(e).__name__}: {e}")
        else:
            ui.error(f"Unknown command {cmd}. Try /help.")
    return None


def undo_turns(arg: str, agent: Agent, ui) -> None:
    """/undo [N]: restore files from checkpoints, then tell the model what happened."""
    if arg and (not arg.isdigit() or int(arg) == 0):
        ui.error("Usage: /undo [N]  (N = how many turns to go back, default 1)")
        return
    changes = checkpoints.undo(int(arg or 1))
    if not changes:
        ui.info("Nothing to undo (only write_file/edit_file changes are tracked, not shell commands).")
        return
    for path, what in changes:
        # The model's view of these files is now stale: make it read them again before editing.
        base.files_read.discard(path)
        ui.info(f"{what}: {path}")
    # Append a user note + model ack as a pair: keeps user/model turns alternating, and the next
    # real message then arrives in the model's context right after it.
    agent.history.append(types.Content(role="user", parts=[types.Part(text=checkpoints.undo_note(changes))]))
    agent.history.append(types.Content(role="model", parts=[types.Part(text="Understood. I'll re-read those files before changing them.")]))
    ui.info("Note: changes made by shell commands (run_shell) are not tracked and were not undone.")


if __name__ == "__main__":
    main()
