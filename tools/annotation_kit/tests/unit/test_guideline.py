"""ml/annotation/phase_guideline.md: structure checks, so what the backlog promises stays true."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from annotation_kit.phases import PHASES
from annotation_kit.ucf import DEFAULT_CLASSES
from vms_common.vqa_bank import DEFAULT_EVENT_TYPE, VQABank

DEPLOYED = ("intrusion", "loitering", "crowding", "abandoned_object", "running")


@pytest.fixture(scope="module")
def guideline(repo: Path) -> str:
    return (repo / "ml/annotation/phase_guideline.md").read_text()


def section(text: str, heading: str) -> str:
    """The body of `### <heading>` up to the next heading of the same or higher level."""
    match = re.search(rf"^### {re.escape(heading)}\s*$(.*?)(?=^#{{1,3}} |\Z)", text, re.S | re.M)
    assert match, f"no '### {heading}' section"
    return match.group(1)


def test_it_says_it_is_a_draft_until_the_guide_approves_the_taxonomy(guideline: str) -> None:
    assert "needs the project guide's approval" in guideline.split("## What you are doing")[0]


def test_the_five_phases_are_defined_in_order(guideline: str) -> None:
    table = section(
        guideline.replace("## The five phases", "### The five phases"), "The five phases"
    )
    rows = re.findall(r"^\| \*\*(\w+)\*\* \|", table, re.M)
    assert tuple(rows) == PHASES


@pytest.mark.parametrize(
    ("heading", "event_type"), [(t.capitalize().replace("_", " "), t) for t in DEPLOYED]
)
def test_every_deployed_event_type_has_three_worked_examples(
    guideline: str, heading: str, event_type: str
) -> None:
    body = section(guideline, heading)
    assert len(re.findall(r"^\*\*[123]\. ", body, re.M)) == 3, event_type


def test_the_worked_examples_only_use_the_five_phases(guideline: str) -> None:
    examples = guideline.split("## Worked examples")[1].split("## Where the clips come from")[0]
    named = set(re.findall(r"^\| (\w+) \| [\d-]+ \|", examples, re.M))
    assert named <= set(PHASES) and named == set(PHASES)


def test_every_default_ucf_class_is_covered_and_the_choice_is_explained(guideline: str) -> None:
    theft = section(guideline, "Theft (and the UCF-Crime classes)")
    for cls in DEFAULT_CLASSES:
        assert re.search(rf"\*\*{cls}\b", theft, re.I), cls
    assert "Chosen because" in guideline and "the other five" in guideline.lower()


def test_it_tells_the_truth_about_meva_and_its_numbers(guideline: str) -> None:
    assert "not an incident dataset" in guideline
    assert "1 clip" in guideline and "4" in guideline and "361" in guideline and "179" in guideline


def test_every_event_type_the_annotator_can_choose_is_mentioned(
    guideline: str, bank: VQABank
) -> None:
    for event_type in bank.event_types:
        if event_type != DEFAULT_EVENT_TYPE:
            assert f"`{event_type}`" in guideline, event_type
    assert "`theft`" in guideline and "`activity`" in guideline


def test_it_says_how_to_measure_agreement_on_twenty_clips(guideline: str) -> None:
    assert "K and P both label the same 20 clips" in guideline
    assert "annotation-kit phase-agreement" in guideline
