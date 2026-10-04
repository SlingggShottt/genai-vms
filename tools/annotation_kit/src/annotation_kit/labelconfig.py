"""The Label Studio labelling configs, generated from the VQA bank.

One config per event type, because the questions differ by event type and a Label Studio config is
static. They are generated, not hand-written, so the questions an annotator verifies cannot drift
from `config/vqa_bank.yaml`, and the converter can rely on the names below.

What an annotator sees for one task (one phase of one clip in one view): the clip, playing just that
phase; a caption box (verify or rewrite the draft); one required choice per question (every question
has "Cannot tell"); and whether the clip is usable at all.

`from_name`s, which `convert.py` reads back: `caption`, each question's id, and `usable`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

from vms_common.vqa_bank import VQABank, VQAQuestion

VIDEO = "video"
CAPTION = "caption"
USABLE = "usable"
USABLE_YES = "Yes"
USABLE_NO = "No"

CAPTION_HELP = (
    "Describe only what is visible in this view during this phase, in one or two sentences. "
    "Say what people and objects do, not who they are or what they intend. "
    "If the draft is right, keep it; if not, rewrite it."
)


def _header(parent: ET.Element, text: str) -> None:
    ET.SubElement(parent, "Header", value=text)


def _choices(parent: ET.Element, name: str, answers: Sequence[str]) -> None:
    choices = ET.SubElement(
        parent,
        "Choices",
        name=name,
        toName=VIDEO,
        choice="single",
        showInline="true",
        required="true",
    )
    for answer in answers:
        ET.SubElement(choices, "Choice", value=answer)


def build_label_config(event_type: str, questions: Sequence[VQAQuestion]) -> str:
    """The Label Studio XML for one event type's questions."""
    view = ET.Element("View")
    _header(view, f"{event_type.replace('_', ' ').capitalize()}: $phase phase, view $view")
    ET.SubElement(view, "Video", name=VIDEO, value="$video", framerate="25")

    _header(view, "Caption")
    # A Header, not a Text: to Label Studio a Text tag is a data object, even with a fixed value.
    _header(view, CAPTION_HELP)
    ET.SubElement(
        view,
        "TextArea",
        name=CAPTION,
        toName=VIDEO,
        rows="3",
        editable="true",
        required="true",
        maxSubmissions="1",
        placeholder="What happens in this view during this phase?",
    )

    for question in questions:
        _header(view, question.text)
        _choices(view, question.id, question.answers)

    _header(view, "Is this clip usable? Choose No if this phase cannot be seen in this view.")
    _choices(view, USABLE, (USABLE_YES, USABLE_NO))

    ET.indent(view, space="  ")
    return ET.tostring(view, encoding="unicode") + "\n"


def write_label_configs(bank: VQABank, out_dir: str | Path) -> list[Path]:
    """Write `<event_type>.xml` for every event type in the bank; returns the paths."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for event_type, questions in bank.event_types.items():
        path = directory / f"{event_type}.xml"
        path.write_text(build_label_config(event_type, questions), encoding="utf-8")
        written.append(path)
    return written
