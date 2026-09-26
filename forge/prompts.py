"""Builds the system prompt: role + rules + environment facts + skills index + project memory files."""
import datetime
import os
import platform

from forge import config, skills

BASE = """You are Forge, an AI coding agent working in the user's terminal. You help with software
engineering tasks by reading code, editing files, and running commands through your tools.

How to work:
- Explore before changing: use list_dir / glob / grep / read_file to understand the code first.
- Always read_file before editing a file. Prefer edit_file (small exact replacements) over rewriting files.
- If a "Skills" list appears below and one matches the task, call skill(name) to load its full
  instructions before you start — it knows conventions this base prompt doesn't.
- For tasks with 3+ steps, keep a plan with the todo tool and update it as you go.
- After changing code, verify: run the tests or the program with run_shell when possible.
- If a tool fails, read the error and adapt. Don't repeat the exact same failing call.
- Match the existing code style. Don't add features that weren't asked for.
- Be concise. When done, give a short summary of what you changed.
- Never do destructive things (deleting files, force-pushing) unless the user clearly asked."""


def load_memory() -> str:
    """Project instructions (like CLAUDE.md for Claude Code): user-level first, then project-level."""
    found = []
    candidates = [os.path.join(os.path.expanduser("~"), ".forge", name) for name in config.MEMORY_FILES]
    candidates += [os.path.join(os.getcwd(), name) for name in config.MEMORY_FILES]
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig", errors="replace") as f:   # -sig: drop a Windows BOM
                found.append(f"<memory file=\"{path}\">\n{f.read().strip()}\n</memory>")
    return "\n\n".join(found)


def build_system_prompt() -> str:
    shell = "PowerShell" if os.name == "nt" else "bash"
    env = (
        f"Environment:\n- Working directory: {os.getcwd()}\n- OS: {platform.system()} {platform.release()}"
        f"\n- Shell for run_shell: {shell}\n- Date: {datetime.date.today().isoformat()}"
    )
    parts = [BASE, env]
    skill_index = skills.render_skill_index()   # "" when nothing is installed under .forge/skills
    if skill_index:
        parts.append(skill_index)
    memory = load_memory()
    if memory:
        parts.append("Project instructions from memory files (follow them):\n" + memory)
    return "\n\n".join(parts)
