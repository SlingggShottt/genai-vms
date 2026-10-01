"""Versioned prompt files: `llm/prompts/<task>/<version>.md`, rendered with Jinja2
(style_guide.md §A.6). Wording changes mean a new version file — old versions stay so
evaluation results that cite them remain reproducible.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import StrictUndefined, TemplateNotFound
from jinja2.sandbox import SandboxedEnvironment

from vms_common.llm.errors import LLMRequestError

PROMPTS_DIR = Path(__file__).parent / "prompts"

_TASK = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION = re.compile(r"^\d+\.\d+$")


class PromptLibrary:
    def __init__(self, root: Path | str = PROMPTS_DIR) -> None:
        self._root = Path(root)
        # Prompts are plain text for a model, not HTML, so autoescaping would corrupt them.
        # Sandboxed + StrictUndefined: a template can't reach into objects, and a variable the
        # caller forgot is an error rather than a silently empty hole in the prompt.
        self._env = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,  # noqa: S701
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )

    def render(self, task: str, version: str, **variables: object) -> str:
        """Render `<root>/<task>/<version>.md`. Names are validated so a task or version taken
        from data can never walk out of the prompts directory."""
        if not _TASK.match(task):
            raise LLMRequestError(f"invalid prompt task name {task!r}")
        if not _VERSION.match(version):
            raise LLMRequestError(f"invalid prompt version {version!r}; expected e.g. '1.0'")
        path = self._root / task / f"{version}.md"
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise LLMRequestError(
                f"no prompt {task}/{version}; have {self.versions(task) or 'none'}"
            ) from None
        try:
            return self._env.from_string(source).render(**variables).strip()
        except TemplateNotFound as exc:  # an {% include %} of a missing file
            raise LLMRequestError(
                f"prompt {task}/{version} includes a missing file: {exc}"
            ) from exc

    def versions(self, task: str) -> list[str]:
        """Available versions of `task`, oldest first."""
        if not _TASK.match(task):
            return []
        found = [p.stem for p in (self._root / task).glob("*.md") if _VERSION.match(p.stem)]
        return sorted(found, key=lambda v: tuple(int(n) for n in v.split(".")))


_default = PromptLibrary()


def render_prompt(task: str, version: str, **variables: object) -> str:
    """Render a packaged prompt, e.g. `render_prompt("event_verify", "1.0", rule=...)`."""
    return _default.render(task, version, **variables)
