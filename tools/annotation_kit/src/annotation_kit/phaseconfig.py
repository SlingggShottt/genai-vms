"""The Label Studio config for marking incident phases on a video timeline (P3-D5).

For each candidate clip the annotator drags out where each of the five phases happens on the
timeline of the primary view, says which view shows the incident best, confirms the event type, and
says whether the clip is usable at all. Phases are contiguous and ordered and any may be empty
(design section 8.2), so there is no label for "nothing": a stretch with no phase is simply left
unmarked.

A task can have several views (MEVA, 2 to 4), each cut to the same moment. Label Studio plays them
independently and has no way to link their timelines, so the config has one `<Video>` per view with
the labelling attached to the first (the suggested primary view); the others are there to look at.
One config per number of views: `phase_labelling_<n>view(s).xml`.

`from_name`s the converter reads back: `phase`, `primary_view`, `event_type`, `usable`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

from annotation_kit.candidates import FPS
from annotation_kit.labelconfig import USABLE, USABLE_NO, USABLE_YES
from annotation_kit.phases import PHASE_DEFINITIONS, PHASES

VIDEO = "video"
PHASE = "phase"
PRIMARY_VIEW = "primary_view"
EVENT_TYPE = "event_type"
MAX_VIEWS = 4
FRAMERATE = FPS  # clips are cut at a constant rate, so a frame number is unambiguous

# Neutral, distinguishable, and deliberately not the severity colours: a phase is structure.
_PHASE_COLOURS = {
    "baseline": "#8ea3b5",
    "precursor": "#6aa6b0",
    "escalation": "#8f8fc4",
    "action": "#b58fb5",
    "aftermath": "#9fb58f",
}


def video_name(index: int) -> str:
    """`video` for the primary view, then `video_2`, `video_3`, ..."""
    return VIDEO if index == 0 else f"{VIDEO}_{index + 1}"


def build_phase_config(event_types: Sequence[str], views: int = 1) -> str:
    """The Label Studio XML for phase labelling, for tasks with `views` views."""
    if not 1 <= views <= MAX_VIEWS:
        raise ValueError(f"views must be 1 to {MAX_VIEWS}, got {views}")
    if len(set(event_types)) != len(event_types) or not event_types:
        raise ValueError("event_types must be a non-empty list without repeats")

    root = ET.Element("View")
    ET.SubElement(root, "Header", value="$event_type: $candidate_id")
    for index in range(views):
        ET.SubElement(
            root,
            "Video",
            name=video_name(index),
            value=f"${video_name(index)}",
            framerate=str(FRAMERATE),
            **({"timelineHeight": "110"} if index == 0 else {}),
        )
    if views > 1:
        ET.SubElement(
            root,
            "Header",
            value="The first video is the one to mark. The others show the same moment from "
            "other cameras: scrub them to the same time to look.",
        )

    ET.SubElement(root, "Header", value="Phases")
    ET.SubElement(
        root,
        "Header",
        value="Drag out each phase on the first video's timeline. Phases go in order, do not "
        "overlap, and may be left out. Leave a stretch unmarked if no phase fits it.",
    )
    labels = ET.SubElement(root, "TimelineLabels", name=PHASE, toName=VIDEO)
    for number, phase in enumerate(PHASES, start=1):
        ET.SubElement(
            labels,
            "Label",
            value=phase,
            hotkey=str(number),
            background=_PHASE_COLOURS[phase],
            # A hint, never an alias: an alias replaces the stored value, so results would carry
            # the definition text instead of the phase name.
            hint=PHASE_DEFINITIONS[phase],
        )

    ET.SubElement(root, "Header", value="Which view shows the incident best?")
    ET.SubElement(
        root,
        "Choices",
        name=PRIMARY_VIEW,
        toName=VIDEO,
        choice="single",
        showInline="true",
        required="true",
        value="$views",
    )

    ET.SubElement(root, "Header", value="What kind of incident is this?")
    kinds = ET.SubElement(
        root, "Choices", name=EVENT_TYPE, toName=VIDEO, choice="single", required="true"
    )
    for event_type in event_types:
        ET.SubElement(kinds, "Choice", value=event_type)

    ET.SubElement(
        root, "Header", value="Is this clip usable? Choose No if no incident can be seen in it."
    )
    usable = ET.SubElement(
        root,
        "Choices",
        name=USABLE,
        toName=VIDEO,
        choice="single",
        showInline="true",
        required="true",
    )
    for answer in (USABLE_YES, USABLE_NO):
        ET.SubElement(usable, "Choice", value=answer)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def config_filename(views: int) -> str:
    return f"phase_labelling_{views}view{'s' if views > 1 else ''}.xml"


def write_phase_configs(event_types: Sequence[str], out_dir: str | Path) -> list[Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for views in range(1, MAX_VIEWS + 1):
        path = directory / config_filename(views)
        path.write_text(build_phase_config(event_types, views), encoding="utf-8")
        paths.append(path)
    return paths
