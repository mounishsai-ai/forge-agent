"""The `skill` tool: load one installed skill's full instructions on demand.

Why this is a separate tool instead of just dumping every skill's body into the system
prompt: progressive disclosure (see forge/skills.py's module docstring). The system prompt
only ever carries a skill's name + description; this tool is how the model spends the extra
tokens for the full SKILL.md body, and it only does that for the one skill it actually needs.
Read-only (needs_permission defaults to False), so sub-agents get it too (forge/tools/__init__.py
includes it in READ_ONLY_TOOLS).
"""
from forge.skills import SkillNotFound, load_skill
from forge.tools.base import Tool, ToolError


def skill(name: str) -> str:
    try:
        return load_skill(name)
    except SkillNotFound as e:
        raise ToolError(str(e)) from e


TOOL = Tool(
    name="skill",
    description=(
        "Load the full instructions for a skill named in the system prompt's 'Skills' list. "
        "Returns the skill's body plus the names of any other files in its folder (read those "
        "with read_file). Call this BEFORE starting work that matches a listed skill's "
        "description — it's the whole instructions, not just the one-line summary."
    ),
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Skill name, exactly as listed in the system prompt."}},
        "required": ["name"],
    },
    run=skill,
)
