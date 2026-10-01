"""Versioned prompt files rendered with Jinja2."""

from __future__ import annotations

from pathlib import Path

import pytest
from vms_common.llm.errors import LLMRequestError
from vms_common.llm.prompts import PROMPTS_DIR, PromptLibrary, render_prompt


@pytest.fixture
def library(tmp_path: Path) -> PromptLibrary:
    (tmp_path / "greet").mkdir()
    (tmp_path / "greet" / "1.0.md").write_text(
        "You are a guard.\n<data>\n{% for c in cameras %}- {{ c }}\n{% endfor %}</data>\n"
        "Rule: {{ rule }}\n",
        encoding="utf-8",
    )
    (tmp_path / "greet" / "1.2.md").write_text("v1.2 {{ rule }}", encoding="utf-8")
    (tmp_path / "greet" / "1.10.md").write_text("v1.10 {{ rule }}", encoding="utf-8")
    (tmp_path / "greet" / "notes.md").write_text("not a version", encoding="utf-8")
    return PromptLibrary(tmp_path)


def test_render_substitutes_variables_and_loops(library: PromptLibrary) -> None:
    text = library.render("greet", "1.0", cameras=["cam01", "cam02"], rule="loitering")
    assert text == "You are a guard.\n<data>\n- cam01\n- cam02\n</data>\nRule: loitering"


def test_a_missing_variable_is_an_error_not_a_silent_hole(library: PromptLibrary) -> None:
    with pytest.raises(Exception, match="rule"):
        library.render("greet", "1.2")


def test_values_are_not_html_escaped(library: PromptLibrary) -> None:
    assert library.render("greet", "1.2", rule="a < b & c") == "v1.2 a < b & c"


def test_template_syntax_inside_a_value_is_not_evaluated(library: PromptLibrary) -> None:
    assert library.render("greet", "1.2", rule="{{ 7 * 7 }}") == "v1.2 {{ 7 * 7 }}"


def test_versions_sort_numerically_not_lexically(library: PromptLibrary) -> None:
    assert library.versions("greet") == ["1.0", "1.2", "1.10"]
    assert library.versions("nope") == []


def test_unknown_prompt_error_lists_what_exists(library: PromptLibrary) -> None:
    with pytest.raises(LLMRequestError, match=r"no prompt greet/9\.9.*1\.0"):
        library.render("greet", "9.9")
    with pytest.raises(LLMRequestError, match="no prompt other/1.0"):
        library.render("other", "1.0")


@pytest.mark.parametrize("task", ["../greet", "greet/../greet", "Greet", "", "a b", "/etc"])
def test_task_names_cannot_escape_the_prompts_directory(library: PromptLibrary, task: str) -> None:
    with pytest.raises(LLMRequestError, match="invalid prompt task"):
        library.render(task, "1.0")
    assert library.versions(task) == []


@pytest.mark.parametrize("version", ["../1.0", "1", "1.0.0", "v1.0", "1.x", ""])
def test_versions_must_look_like_major_dot_minor(library: PromptLibrary, version: str) -> None:
    with pytest.raises(LLMRequestError, match="invalid prompt version"):
        library.render("greet", version)


def test_sandbox_blocks_reaching_into_objects(library: PromptLibrary, tmp_path: Path) -> None:
    (tmp_path / "evil").mkdir()
    (tmp_path / "evil" / "1.0.md").write_text("{{ x.__class__.__mro__ }}", encoding="utf-8")
    with pytest.raises(Exception, match="unsafe|__class__"):
        library.render("evil", "1.0", x="a")


def test_packaged_prompts_directory_exists_for_later_stories() -> None:
    assert PROMPTS_DIR.is_dir()
    with pytest.raises(LLMRequestError):
        render_prompt("not_a_task", "1.0")
