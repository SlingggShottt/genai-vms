"""Label Studio export -> `phavr_labels.jsonl`.

Reads the JSON export of a caption/VQA project (Export > JSON), and keeps, for every task, the last
non-cancelled annotation (people may correct themselves; a task two people labelled is resolved to
the later one, and the overlap sets used for agreement are measured elsewhere). A task becomes a
label only if it is complete: usable, a caption, and a valid answer to every question the bank asks
for its event type. Anything else is skipped *and counted by reason*, so a lost label is visible.

The model's draft (the task's first prediction) is kept beside the verified label with how far the
person moved it, which is what `report.py` turns into the edit rate.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from vms_common.vqa_bank import VQABank

from annotation_kit.labelconfig import CAPTION, USABLE, USABLE_NO
from annotation_kit.schema import CaptionVqaTask, Edits, PhavrLabel, PseudoLabel, VqaItem

SKIP_REASONS = ("no_annotation", "cancelled", "unusable", "no_caption", "incomplete")


@dataclass
class Converted:
    labels: list[PhavrLabel] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(
        default_factory=lambda: defaultdict(list)
    )  # reason -> task keys

    @property
    def tasks(self) -> int:
        return len(self.labels) + sum(len(keys) for keys in self.skipped.values())


def normalise(text: str) -> str:
    """Case, punctuation and spacing are not an edit: adding a full stop is not a rewrite."""
    return " ".join(re.sub(r"[^\w\s]", "", text.casefold()).split())


def similarity(a: str, b: str) -> float:
    """1.0 for the same words, 0.0 for no words in common: how much of the caption was kept.

    Compared word by word, not letter by letter: letters would score two unrelated captions well
    above zero just for sharing spaces, and "how many words did a person change" is what is meant.
    """
    words_a, words_b = normalise(a).split(), normalise(b).split()
    if not words_a and not words_b:
        return 1.0
    return SequenceMatcher(None, words_a, words_b, autojunk=False).ratio()


def _read_result(result: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, str]]:
    """Caption text and `{control name: chosen answer}` from a Label Studio `result` list."""
    caption = ""
    choices: dict[str, str] = {}
    for item in result:
        name = item.get("from_name")
        value = item.get("value") or {}
        if item.get("type") == "textarea" and name == CAPTION:
            caption = " ".join(" ".join(value.get("text") or []).split())
        elif item.get("type") == "choices" and isinstance(name, str) and value.get("choices"):
            choices[name] = value["choices"][0]
    return caption, choices


def _latest(annotations: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    return max(annotations, key=lambda a: (str(a.get("updated_at") or ""), int(a.get("id") or 0)))


def _annotator(annotation: Mapping[str, Any]) -> str | None:
    by = annotation.get("completed_by")
    if isinstance(by, Mapping):
        by = by.get("email") or by.get("id")
    return None if by is None else str(by)


def convert(export: Sequence[Mapping[str, Any]], bank: VQABank) -> Converted:
    out = Converted()
    for item in export:
        task = CaptionVqaTask.model_validate(item["data"])
        annotations = [a for a in item.get("annotations") or [] if not a.get("was_cancelled")]
        if not item.get("annotations"):
            out.skipped["no_annotation"].append(task.key)
            continue
        annotations = [a for a in annotations if a.get("result")]
        if not annotations:
            out.skipped["cancelled"].append(task.key)
            continue

        annotation = _latest(annotations)
        caption, choices = _read_result(annotation["result"])
        if choices.get(USABLE) == USABLE_NO:
            out.skipped["unusable"].append(task.key)
            continue
        if not caption:
            out.skipped["no_caption"].append(task.key)
            continue
        questions = bank.questions_for(task.event_type)
        if any(choices.get(q.id) not in q.answers for q in questions):
            out.skipped["incomplete"].append(task.key)
            continue

        pseudo, edits = _pseudo_and_edits(item, caption, choices, questions)
        out.labels.append(
            PhavrLabel(
                clip_id=task.clip_id,
                source_video=task.source_video,
                event_type=task.event_type,
                view=task.view,
                phase=task.phase,
                start_s=task.start_s,
                end_s=task.end_s,
                caption=caption,
                vqa=[VqaItem(id=q.id, q=q.text, a=choices[q.id]) for q in questions],
                pseudo=pseudo,
                edits=edits,
                annotator=_annotator(annotation),
            )
        )
    return out


def _pseudo_and_edits(
    item: Mapping[str, Any], caption: str, choices: Mapping[str, str], questions: Sequence[Any]
) -> tuple[PseudoLabel | None, Edits | None]:
    prediction = next((p for p in item.get("predictions") or [] if p.get("result")), None)
    if prediction is None:
        return None, None
    draft_caption, draft_choices = _read_result(prediction["result"])
    draft_answers = {q.id: draft_choices[q.id] for q in questions if q.id in draft_choices}
    pseudo = PseudoLabel(
        model_version=str(prediction.get("model_version") or "unknown"),
        caption=draft_caption,
        vqa=draft_answers,
    )
    edits = Edits(
        caption_changed=normalise(caption) != normalise(draft_caption),
        caption_similarity=similarity(caption, draft_caption),
        answers_changed=[q.id for q in questions if draft_answers.get(q.id) != choices[q.id]],
    )
    return pseudo, edits


def read_export(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: a Label Studio export is a JSON list of tasks")
    return data


def write_jsonl(labels: Iterable[PhavrLabel], path: str | Path) -> int:
    count = 0
    with open(path, "w", encoding="utf-8") as handle:
        for label in labels:
            handle.write(label.model_dump_json() + "\n")
            count += 1
    return count
