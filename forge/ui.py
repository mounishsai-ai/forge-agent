"""Everything the user sees. The agent never prints directly; it calls these methods.

That separation lets the same agent run in the interactive terminal (ConsoleUI)
or silently in headless mode / evals (QuietUI).
"""
import json
from contextlib import contextmanager

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()


def _short_args(args: dict, limit: int = 100) -> str:
    """One-line preview of tool arguments, e.g. path='src/app.py'."""
    parts = []
    for k, v in args.items():
        s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v.replace("\n", "\\n")
        parts.append(f"{k}={s[:60]}{'...' if len(s) > 60 else ''}")
    line = ", ".join(parts)
    return line[:limit] + ("..." if len(line) > limit else "")


class ConsoleUI:
    def assistant_text(self, text: str) -> None:
        if text.strip():
            console.print(Markdown(text))

    def tool_call(self, name: str, args: dict) -> None:
        console.print(f"[bold cyan]> {name}[/]([dim]{_short_args(args)}[/])")

    def tool_result(self, name: str, output: str, ok: bool) -> None:
        lines = output.splitlines()
        preview = "\n".join(lines[:4]) + (f"\n  ... ({len(lines) - 4} more lines)" if len(lines) > 4 else "")
        style = "dim" if ok else "red"
        console.print(f"[{style}]  {preview.replace(chr(10), chr(10) + '  ')}[/]", highlight=False)

    def ask_permission(self, name: str, args: dict) -> str:
        if name == "run_shell":
            body = Syntax(args.get("command", ""), "powershell", word_wrap=True)
        elif name == "edit_file":
            body = f"[red]- {args.get('old_string', '')}[/]\n[green]+ {args.get('new_string', '')}[/]"
        elif name == "write_file":
            content = args.get("content", "")
            body = f"{args.get('path')}  ({len(content.splitlines())} lines)\n[dim]{content[:800]}[/]"
        else:
            body = json.dumps(args, indent=2)[:1500]
        console.print(Panel(body, title=f"[yellow]Allow {name}?[/]", border_style="yellow"))
        while True:
            ans = console.input("[yellow](y)es / (n)o / (a)lways for this tool: [/]").strip().lower()
            if ans in ("y", "n", "a"):
                return ans

    def info(self, msg: str) -> None:
        console.print(f"[dim]{msg}[/]")

    def error(self, msg: str) -> None:
        console.print(f"[bold red]{msg}[/]")

    @contextmanager
    def thinking(self):
        with console.status("[dim]thinking...[/]", spinner="dots"):
            yield


class QuietUI(ConsoleUI):
    """For headless runs: no output except errors; permission requests are denied (use --yes to allow)."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def assistant_text(self, text): pass

    def tool_call(self, name, args):
        if self.verbose:
            super().tool_call(name, args)

    def tool_result(self, name, output, ok): pass

    def ask_permission(self, name, args):
        return "n"

    def info(self, msg): pass

    @contextmanager
    def thinking(self):
        yield
