"""Decides whether a tool call may run. This is the harness's safety layer.

Modes:
  ask      - read-only tools run freely; writes/shell ask the user (y / n / a = always for this tool)
  auto     - everything runs without asking (used for evals / headless), except the blocklist
  readonly - anything that changes the machine is refused
The blocklist is checked in EVERY mode: some commands are never worth the risk.
"""
import re

from forge.tools.base import Tool

BLOCKLIST = [
    # recursive rm (any flag order/splitting) aimed at /, /*, ~, $HOME or a bare *
    r"\brm\s+(?=(?:[^;&|]*\s)?-[a-zA-Z]*[rR])[^;&|]*\s(/|/\*|~/?|~/\*|\$HOME/?|\*)(\s|;|&|\||$)",
    r"Remove-Item\b.*-Recurse.*\b[A-Za-z]:\\?\s*$",      # wipe a whole drive
    # Disk/power commands only when they are the command being run (start of line, after ; & | or sudo),
    # so `git log --pretty=format:%H` or `grep shutdown app.py` are not blocked.
    r"\bformat(\.com)?\s+[A-Za-z]:",
    r"(^|[;&|]\s*|sudo\s+)(mkfs(\.\w+)?|diskpart|shutdown|reboot|poweroff|halt)\b",
    r"(^|[;&|]\s*)(Stop-Computer|Restart-Computer)\b",
    r"git\s+push\b.*(--force|-f\b)",
    r":\(\)\s*\{\s*:\|:&\s*\};:",                        # fork bomb
]


class Permissions:
    def __init__(self, mode: str = "ask"):
        assert mode in ("ask", "auto", "readonly")
        self.mode = mode
        self.always_allowed: set[str] = set()   # tool names the user said "always" to this session

    def check(self, tool: Tool, args: dict, ui) -> tuple[bool, str]:
        """Returns (allowed, reason). The reason goes back to the model if denied."""
        if tool.name == "run_shell":
            cmd = args.get("command", "")
            for pattern in BLOCKLIST:
                if re.search(pattern, cmd, re.IGNORECASE):
                    return False, f"Blocked: command matches a dangerous pattern ({pattern})."

        if not tool.needs_permission:
            return True, ""
        if self.mode == "readonly":   # checked before "always": read-only must override earlier approvals
            return False, "Denied: Forge is in read-only mode."
        if self.mode == "auto" or tool.name in self.always_allowed:
            return True, ""

        answer = ui.ask_permission(tool.name, args)   # 'y', 'n' or 'a'
        if answer == "a":
            self.always_allowed.add(tool.name)
            return True, ""
        if answer == "y":
            return True, ""
        return False, "The user denied this action. Ask them what they want instead, or try another approach."
