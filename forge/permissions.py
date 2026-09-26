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
        self.plan_mode = False        # True between /plan (or --plan) and an approved exit_plan call
        self._pre_plan_mode: str | None = None   # self.mode as it was before plan mode, to restore on exit

    def enter_plan_mode(self) -> None:
        """Force read-only and remember the mode to go back to. Idempotent: calling it again
        while already in plan mode must not overwrite the saved pre-plan mode with "readonly"."""
        if self.plan_mode:
            return
        self._pre_plan_mode = self.mode
        self.plan_mode = True
        self.mode = "readonly"   # `check()` below needs no new branch: readonly already denies writes/shell

    def exit_plan_mode(self, approved: bool) -> None:
        """Called by the exit_plan tool (forge/tools/exit_plan.py) once the user has answered,
        and by cli.py's `/plan` toggle-off (always with approved=True: leaving manually needs no
        plan). On rejection we deliberately stay in plan mode/readonly so the model keeps exploring."""
        if not self.plan_mode or not approved:
            return
        self.plan_mode = False
        self.mode = self._pre_plan_mode or "ask"
        self._pre_plan_mode = None

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
