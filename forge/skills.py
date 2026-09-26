"""Skills and custom slash commands: both are just files under `.forge/` (project) or
`~/.forge/` (user) that a human drops in without touching Forge's own code — the same idea
as `FORGE.md`/`AGENTS.md` project memory in `prompts.py`, but for packaged, on-demand
instructions instead of always-on ones. See docs/ARCHITECTURE.md for the full design writeup.

Skills (mirrors Claude Code's skills):
    .forge/skills/<name>/SKILL.md   (project)     ~/.forge/skills/<name>/SKILL.md   (user)
    ---
    name: write-tests
    description: Conventions for writing pytest tests in this repo.
    ---
    <body: the full instructions>

Only `name` + `description` from every installed skill go into the system prompt
(`render_skill_index`) — that's "progressive disclosure": the always-on cost is one short menu
line per INSTALLED skill (plus a fixed, constant cost elsewhere: one BASE sentence and the
`skill` tool's own schema, present whether or not any skill exists), and the model only pays the
much larger token cost of a skill's full body (its `SKILL.md` after the frontmatter, read on
demand via the `skill` tool in `forge/tools/skill.py`) once it has actually decided a task
matches one of the listed descriptions. Stuffing every skill's full body into the system prompt
up front would defeat the point of having skills at all — the context budget would grow with the
number of skills installed, not with the number actually USED in a given task. (Not literally
free: with zero skills installed there's still that one fixed BASE sentence and tool schema; what
scales to exactly zero is the per-skill index and every skill's full body.)

Custom slash commands:
    .forge/commands/<name>.md   (project)     ~/.forge/commands/<name>.md   (user)
    <file contents, with $ARGUMENTS replaced by whatever the user typed after the command name>
Typing `/<name> some args` in the REPL sends the rendered file as the next user message
(wired up in `cli.py`, kept minimal there — the actual discovery/rendering lives here).
"""
import os
from dataclasses import dataclass


class SkillNotFound(Exception):
    """Raised by load_skill for an unknown name. Caught in forge/tools/skill.py and turned
    into a ToolError there — this module stays free of any tools/ import so it can also be
    used from prompts.py and cli.py without a circular import."""


@dataclass
class Skill:
    name: str
    description: str
    dir: str    # absolute path to the skill's folder (SKILL.md's sibling files live here too)
    path: str   # absolute path to SKILL.md itself


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md file into its frontmatter dict and body.

    Real YAML frontmatter would need PyYAML, an extra dependency, for the sake of two flat
    string fields (`name`, `description`). Skill/command frontmatter here is always
    `---\\nkey: value\\n...\\n---`, so a few lines of string splitting is the whole parser —
    no library, nothing to get wrong with nested structures we don't use anyway.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    meta: dict = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        key, sep, value = lines[i].partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"').strip("'")
        i += 1
    if i == len(lines):   # no closing "---": not frontmatter, don't swallow the whole file as meta
        return {}, text.strip()
    body ="\n".join(lines[i + 1:]).strip()
    return meta, body


def _search_roots(leaf: str) -> list[str]:
    """User-level directory first, then project-level — same convention as
    prompts.load_memory (user, then cwd). Callers that build a name->item dict from these,
    in this order, get "project overrides user on a name collision" for free, because the
    later entry simply overwrites the earlier one in the dict."""
    return [
        os.path.join(os.path.expanduser("~"), ".forge", leaf),
        os.path.join(os.getcwd(), ".forge", leaf),
    ]


def discover_skills() -> dict[str, Skill]:
    """Scan both skill directories. Returns {name: Skill}; a project skill with the same
    name as a user skill wins (see _search_roots)."""
    found: dict[str, Skill] = {}
    for base in _search_roots("skills"):
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            skill_md = os.path.join(base, entry, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            # utf-8-sig: PowerShell's Out-File/Set-Content default to a UTF-8 BOM on Windows
            # (see CLAUDE.local.md environment notes); a plain "utf-8" decode would leave the
            # BOM on the first line, so lines[0] != "---" and the whole frontmatter is missed.
            with open(skill_md, encoding="utf-8-sig", errors="replace") as f:
                meta, _ = _parse_frontmatter(f.read())
            name = meta.get("name") or entry
            found[name] = Skill(
                name=name,
                description=meta.get("description", ""),
                dir=os.path.dirname(skill_md),
                path=skill_md,
            )
    return found


def render_skill_index(skills: dict[str, Skill] | None = None) -> str:
    """The bit that goes in the system prompt: name + description only. Returns "" when no
    skills are installed, so a project with none doesn't pay even a few lines of prompt
    tokens for a feature it isn't using."""
    skills = discover_skills() if skills is None else skills
    if not skills:
        return ""
    lines = [f"- {s.name}: {s.description}" for s in skills.values()]
    return (
        "Skills (call the skill tool with a name below to load its full instructions BEFORE "
        "starting matching work; only name+description are preloaded here to keep this "
        "prompt small):\n" + "\n".join(lines)
    )


def load_skill(name: str) -> str:
    """Full body of one skill's SKILL.md (frontmatter stripped), plus a listing of any other
    files in its folder so the model knows they exist and can read_file them by path.
    Used by forge/tools/skill.py, the tool the model actually calls."""
    skills = discover_skills()
    skill = skills.get(name)
    if skill is None:
        available = ", ".join(sorted(skills)) or "(none installed)"
        raise SkillNotFound(f"No skill named '{name}'. Available: {available}")
    with open(skill.path, encoding="utf-8-sig", errors="replace") as f:
        _, body = _parse_frontmatter(f.read())
    # Absolute paths, not bare filenames: read_file resolves a relative path against the
    # CURRENT WORKING DIRECTORY, not the skill's folder, and a user-level skill lives under
    # ~/.forge/ which is nowhere near cwd -- a bare "reference.py" would 404. glob/grep can't
    # find these either, since ".forge" is in tools/base.IGNORED_DIRS. The absolute path is
    # the only way the model can actually reach the file.
    others = sorted(
        os.path.join(skill.dir, n) for n in os.listdir(skill.dir)
        if n != "SKILL.md" and os.path.isfile(os.path.join(skill.dir, n))
    )
    if others:
        body += "\n\nOther files in this skill's folder (read_file with this exact path):\n" \
            + "\n".join(others)
    return body


def discover_commands() -> dict[str, str]:
    """{command name (no slash, no .md) : absolute path to the .md file}. Project overrides
    user on a name collision, same as discover_skills."""
    found: dict[str, str] = {}
    for base in _search_roots("commands"):
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            if entry.endswith(".md"):
                found[entry[:-3]] = os.path.join(base, entry)
    return found


def render_command(path: str, args: str) -> str:
    """Read a command file and substitute $ARGUMENTS with whatever followed the command name
    on the REPL line (e.g. "/review auth.py" -> args="auth.py"). No escaping/quoting: this is
    a plain string replacement, so a command file that uses "$ARGUMENTS" literally elsewhere
    for some other purpose would also get replaced -- an accepted limitation given how small
    this feature is meant to be."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    return text.replace("$ARGUMENTS", args)
