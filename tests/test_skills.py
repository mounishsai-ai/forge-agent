"""Offline tests for forge/skills.py: frontmatter parsing, skill/command discovery
(project overrides user, same convention as prompts.load_memory), and rendering.

Nothing here touches the network or the real home directory / cwd — every test gets its
own tmp_path "home" and "project" via the `roots` fixture below, which monkeypatches
os.path.expanduser and os.chdir the same way a real Forge install would see
~/.forge/skills and <project>/.forge/skills.
"""
import os

import pytest

from forge import cli, skills
from forge.prompts import build_system_prompt
from forge.tools import skill as skill_tool
from forge.tools.base import ToolError


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Fake ~ and cwd, isolated per test. Returns (home_dir, project_dir) as Path objects."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) if p == "~" else p)
    monkeypatch.chdir(project)
    return home, project


def write_skill(base, name, frontmatter: dict, body: str, extra_files: dict | None = None):
    """Create <base>/.forge/skills/<name>/SKILL.md with the given frontmatter + body."""
    d = base / ".forge" / "skills" / name
    d.mkdir(parents=True)
    fm = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n\n{body}\n", encoding="utf-8")
    for fname, content in (extra_files or {}).items():
        (d / fname).write_text(content, encoding="utf-8")
    return d


def write_command(base, name, content):
    d = base / ".forge" / "commands"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------
def test_parse_frontmatter_basic():
    text = '---\nname: write-tests\ndescription: pytest conventions\n---\n\n# Body\ntext here\n'
    meta, body = skills._parse_frontmatter(text)
    assert meta == {"name": "write-tests", "description": "pytest conventions"}
    assert body == "# Body\ntext here"


def test_parse_frontmatter_quoted_value_is_unquoted():
    text = '---\nname: "quoted-name"\n---\nbody\n'
    meta, _ = skills._parse_frontmatter(text)
    assert meta["name"] == "quoted-name"


def test_parse_frontmatter_missing_entirely_returns_whole_text_as_body():
    text = "# Just a heading\nno frontmatter here\n"
    meta, body = skills._parse_frontmatter(text)
    assert meta == {}
    assert body == text.strip()


def test_parse_frontmatter_empty_string():
    meta, body = skills._parse_frontmatter("")
    assert meta == {}
    assert body == ""


# ---------------------------------------------------------------------------
# discover_skills
# ---------------------------------------------------------------------------
def test_discover_skills_empty_when_no_dirs(roots):
    assert skills.discover_skills() == {}


def test_discover_skills_finds_project_skill(roots):
    _, project = roots
    write_skill(project, "write-tests", {"name": "write-tests", "description": "pytest rules"}, "Body text")
    found = skills.discover_skills()
    assert set(found) == {"write-tests"}
    assert found["write-tests"].description == "pytest rules"


def test_discover_skills_finds_user_skill(roots):
    home, _ = roots
    write_skill(home, "git-commit", {"name": "git-commit", "description": "commit style"}, "Body")
    found = skills.discover_skills()
    assert "git-commit" in found


def test_discover_skills_project_overrides_user_on_name_clash(roots):
    home, project = roots
    write_skill(home, "write-tests", {"name": "write-tests", "description": "USER VERSION"}, "user body")
    write_skill(project, "write-tests", {"name": "write-tests", "description": "PROJECT VERSION"}, "project body")
    found = skills.discover_skills()
    assert len(found) == 1
    assert found["write-tests"].description == "PROJECT VERSION"


def test_discover_skills_falls_back_to_folder_name_when_frontmatter_has_no_name(roots):
    _, project = roots
    write_skill(project, "my-folder", {"description": "no explicit name field"}, "Body")
    found = skills.discover_skills()
    assert "my-folder" in found


def test_discover_skills_ignores_folder_without_skill_md(roots):
    _, project = roots
    (project / ".forge" / "skills" / "empty-folder").mkdir(parents=True)
    assert skills.discover_skills() == {}


# ---------------------------------------------------------------------------
# render_skill_index
# ---------------------------------------------------------------------------
def test_render_skill_index_empty_when_none_installed(roots):
    assert skills.render_skill_index() == ""


def test_render_skill_index_lists_name_and_description(roots):
    _, project = roots
    write_skill(project, "write-tests", {"name": "write-tests", "description": "pytest rules"}, "Body")
    out = skills.render_skill_index()
    assert "write-tests: pytest rules" in out
    # Progressive disclosure: the index must NOT leak the full body into the prompt.
    assert "Body" not in out


# ---------------------------------------------------------------------------
# load_skill
# ---------------------------------------------------------------------------
def test_load_skill_returns_body_without_frontmatter(roots):
    _, project = roots
    write_skill(project, "write-tests", {"name": "write-tests", "description": "d"}, "# Heading\nInstructions.")
    out = skills.load_skill("write-tests")
    assert "# Heading" in out
    assert "Instructions." in out
    assert "description:" not in out


def test_load_skill_lists_sibling_files_as_absolute_readable_paths(roots):
    """The listed path must actually work with read_file, not just contain the filename --
    read_file resolves relative paths against cwd, not the skill's folder, so a bare
    "reference.py" would 404 for a user-level skill under ~/.forge/."""
    _, project = roots
    write_skill(project, "write-tests", {"name": "write-tests", "description": "d"}, "Body",
                extra_files={"reference.py": "# example code\n"})
    out = skills.load_skill("write-tests")
    listed = [line.strip() for line in out.splitlines() if line.strip().endswith("reference.py")]
    assert listed, f"no reference.py path found in:\n{out}"
    assert os.path.isabs(listed[0])
    from forge.tools import read_file as read_file_module
    assert "example code" in read_file_module.read_file(listed[0])


def test_load_skill_unknown_name_raises(roots):
    with pytest.raises(skills.SkillNotFound):
        skills.load_skill("does-not-exist")


def test_load_skill_error_message_lists_available_names(roots):
    _, project = roots
    write_skill(project, "write-tests", {"name": "write-tests", "description": "d"}, "Body")
    with pytest.raises(skills.SkillNotFound, match="write-tests"):
        skills.load_skill("nope")


# ---------------------------------------------------------------------------
# discover_commands / render_command
# ---------------------------------------------------------------------------
def test_discover_commands_empty_when_none(roots):
    assert skills.discover_commands() == {}


def test_discover_commands_finds_project_and_user(roots):
    home, project = roots
    write_command(home, "review", "review this: $ARGUMENTS")
    write_command(project, "deploy", "deploy: $ARGUMENTS")
    found = skills.discover_commands()
    assert set(found) == {"review", "deploy"}


def test_discover_commands_project_overrides_user_on_name_clash(roots):
    home, project = roots
    write_command(home, "review", "USER VERSION $ARGUMENTS")
    write_command(project, "review", "PROJECT VERSION $ARGUMENTS")
    found = skills.discover_commands()
    assert len(found) == 1
    assert skills.render_command(found["review"], "") == "PROJECT VERSION "


def test_render_command_substitutes_arguments(roots):
    _, project = roots
    write_command(project, "review", "Please review: $ARGUMENTS\nThanks.")
    path = skills.discover_commands()["review"]
    out = skills.render_command(path, "auth.py")
    assert out == "Please review: auth.py\nThanks."


def test_render_command_with_no_arguments_placeholder_is_unchanged(roots):
    _, project = roots
    write_command(project, "hello", "Just say hello, no placeholder here.")
    path = skills.discover_commands()["hello"]
    out = skills.render_command(path, "ignored args")
    assert out == "Just say hello, no placeholder here."


# ---------------------------------------------------------------------------
# UTF-8 BOM: PowerShell's Out-File/Set-Content default to a BOM on Windows
# (see CLAUDE.local.md environment notes), which a plain "utf-8" decode does not strip.
# ---------------------------------------------------------------------------
def test_discover_skills_handles_utf8_bom(roots):
    _, project = roots
    d = project / ".forge" / "skills" / "write-tests"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: write-tests\ndescription: pytest rules\n---\n\nBody\n", encoding="utf-8-sig",
    )
    found = skills.discover_skills()
    assert found["write-tests"].description == "pytest rules"


def test_load_skill_handles_utf8_bom(roots):
    _, project = roots
    d = project / ".forge" / "skills" / "write-tests"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: write-tests\ndescription: d\n---\n\n# Body heading\n", encoding="utf-8-sig",
    )
    out = skills.load_skill("write-tests")
    assert "# Body heading" in out
    assert "description:" not in out


def test_render_command_handles_utf8_bom(roots):
    _, project = roots
    d = project / ".forge" / "commands"
    d.mkdir(parents=True)
    (d / "review.md").write_text("Review: $ARGUMENTS", encoding="utf-8-sig")
    out = skills.render_command(str(d / "review.md"), "auth.py")
    assert out == "Review: auth.py"


# ---------------------------------------------------------------------------
# forge/tools/skill.py: the tool the model actually calls
# ---------------------------------------------------------------------------
def test_skill_tool_returns_body(roots):
    _, project = roots
    write_skill(project, "write-tests", {"name": "write-tests", "description": "d"}, "Body text")
    assert "Body text" in skill_tool.skill("write-tests")


def test_skill_tool_raises_tool_error_not_skill_not_found(roots):
    """The agent loop (forge/agent.py) only knows to catch ToolError for expected tool
    failures -- a bare SkillNotFound leaking out of the tool would be caught by agent.py's
    last-resort `except Exception`, which still works, but ToolError is the documented,
    intentional contract every other tool in forge/tools/ follows."""
    with pytest.raises(ToolError):
        skill_tool.skill("does-not-exist")


# ---------------------------------------------------------------------------
# forge/prompts.py: progressive disclosure end-to-end
# ---------------------------------------------------------------------------
def test_system_prompt_has_no_skills_index_when_none_installed(roots):
    """BASE always has one generic sentence mentioning the skill tool (cheap, constant-size);
    what must scale with zero when nothing is installed is the actual index block."""
    prompt = build_system_prompt()
    assert skills.render_skill_index() == ""
    assert "Skills (call the skill tool" not in prompt


def test_system_prompt_includes_index_but_not_full_body(roots):
    _, project = roots
    write_skill(project, "write-tests", {"name": "write-tests", "description": "pytest rules"},
                "SECRET_BODY_MARKER should not appear in the system prompt")
    prompt = build_system_prompt()
    assert "write-tests: pytest rules" in prompt
    assert "SECRET_BODY_MARKER" not in prompt


# ---------------------------------------------------------------------------
# forge/cli.py: custom slash commands (built-ins always win; dispatch via agent.run)
# ---------------------------------------------------------------------------
class _StubAgent:
    """Just enough of Agent's interface for handle_command's built-ins and the custom-command
    dispatch path -- a real Agent needs a live LLM, which these tests must not touch."""

    def __init__(self):
        self.history = ["not empty"]
        self.last_prompt_tokens = 42
        self.run_calls = []

    def run(self, text):
        self.run_calls.append(text)
        return "ok"


def test_handle_command_dispatches_custom_command_with_arguments_substituted(roots, fake_ui):
    _, project = roots
    write_command(project, "review", "Please review: $ARGUMENTS")
    agent = _StubAgent()
    cli.handle_command("/review auth.py", agent, fake_ui)
    assert agent.run_calls == ["Please review: auth.py"]


def test_handle_command_unknown_slash_with_no_matching_file_errors(roots, fake_ui):
    agent = _StubAgent()
    cli.handle_command("/nope", agent, fake_ui)
    assert agent.run_calls == []
    assert fake_ui.errors


def test_handle_command_builtin_takes_precedence_over_same_named_custom_command(roots, fake_ui):
    """/clear is a built-in that clears agent.history directly; a same-named
    .forge/commands/clear.md must NOT shadow it -- handle_command's elif chain checks
    built-ins first and only falls through to custom commands in the final else."""
    _, project = roots
    write_command(project, "clear", "this should never be sent to the model: $ARGUMENTS")
    agent = _StubAgent()
    cli.handle_command("/clear", agent, fake_ui)
    assert agent.run_calls == []          # the custom command's content was never sent
    assert agent.history == []            # the built-in /clear ran instead
