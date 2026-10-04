from __future__ import annotations

import json

import pytest
from annotation_kit.report import EditReport, EditStats, edit_report, render_markdown
from annotation_kit.schema import Edits, PhavrLabel, PseudoLabel, VqaItem


def label(
    *,
    event_type: str = "intrusion",
    caption_changed: bool = False,
    similarity: float = 1.0,
    changed: tuple[str, ...] = (),
    drafted: bool = True,
    answers: int = 4,
) -> PhavrLabel:
    ids = [f"{event_type}.q{n}" for n in range(answers)]
    return PhavrLabel(
        clip_id="c",
        source_video="s",
        event_type=event_type,
        view="cam02",
        phase="action",
        start_s=0,
        end_s=1,
        caption="A caption.",
        vqa=[VqaItem(id=i, q="Q?", a="Yes") for i in ids],
        pseudo=PseudoLabel(model_version="m", caption="Draft.", vqa={i: "Yes" for i in ids})
        if drafted
        else None,
        edits=Edits(
            caption_changed=caption_changed,
            caption_similarity=similarity,
            answers_changed=[f"{event_type}.q{n}" for n in map(int, changed)],
        )
        if drafted
        else None,
        annotator="k",
    )


class TestTheRates:
    def test_nothing_changed_is_a_zero_edit_rate_and_all_untouched(self) -> None:
        report = edit_report([label(), label()])
        o = report.overall
        assert (o.labels, o.drafted) == (2, 2)
        assert o.caption_edit_rate == 0.0
        assert o.caption_mean_dissimilarity == 0.0
        assert o.answer_change_rate == 0.0
        assert o.untouched_rate == 1.0

    def test_caption_edit_rate_is_the_share_of_drafted_labels_whose_caption_changed(self) -> None:
        report = edit_report(
            [label(caption_changed=True), label(), label(), label(caption_changed=True)]
        )
        assert report.overall.caption_edit_rate == 0.5

    def test_mean_dissimilarity_averages_every_drafted_label_including_untouched_ones(self) -> None:
        report = edit_report([label(caption_changed=True, similarity=0.2), label()])
        assert report.overall.caption_mean_dissimilarity == pytest.approx(0.4)  # (0.8 + 0) / 2

    def test_answer_change_rate_is_changed_answers_over_all_answers(self) -> None:
        report = edit_report([label(changed=("0", "1")), label(answers=6)])  # 2 changed of 4 + 6
        assert report.overall.answer_change_rate == pytest.approx(2 / 10)

    def test_untouched_means_neither_the_caption_nor_any_answer_changed(self) -> None:
        report = edit_report(
            [label(), label(caption_changed=True), label(changed=("2",)), label(), label()]
        )
        assert report.overall.untouched_rate == pytest.approx(3 / 5)

    def test_a_label_with_no_draft_is_counted_but_not_averaged_in(self) -> None:
        report = edit_report(
            [label(caption_changed=True), label(drafted=False), label(drafted=False)]
        )
        o = report.overall
        assert (o.labels, o.drafted) == (3, 1)
        assert o.caption_edit_rate == 1.0  # one drafted label, and its caption changed
        assert (
            o.answer_change_rate == 0.0
        )  # only the drafted label's 4 answers are in the denominator

    def test_with_no_drafts_at_all_the_rates_are_unknown_not_zero(self) -> None:
        o = edit_report([label(drafted=False)]).overall
        assert o.drafted == 0
        assert o.caption_edit_rate is None
        assert o.caption_mean_dissimilarity is None
        assert o.answer_change_rate is None
        assert o.untouched_rate is None

    def test_no_labels_at_all(self) -> None:
        report = edit_report([])
        assert report.overall.labels == 0 and report.by_event_type == {}


class TestByEventType:
    def test_each_event_type_has_its_own_rates(self) -> None:
        report = edit_report(
            [
                label(event_type="intrusion", caption_changed=True),
                label(event_type="intrusion"),
                label(event_type="running"),
            ]
        )
        assert set(report.by_event_type) == {"intrusion", "running"}
        assert report.by_event_type["intrusion"].caption_edit_rate == 0.5
        assert report.by_event_type["running"].caption_edit_rate == 0.0
        assert report.overall.labels == 3

    def test_the_overall_figures_are_over_every_event_type(self) -> None:
        report = edit_report(
            [
                label(event_type="intrusion", changed=("0",)),
                label(event_type="running", changed=("0", "1")),
            ]
        )
        assert report.overall.answer_change_rate == pytest.approx(3 / 8)


class TestSkipped:
    def test_counts_by_reason_and_leaves_out_reasons_with_none(self) -> None:
        report = edit_report(
            [], skipped={"unusable": ["a", "b"], "incomplete": [], "no_caption": ["c"]}
        )
        assert report.skipped == {"unusable": 2, "no_caption": 1}


class TestAsJson:
    def test_has_the_overall_by_type_and_skipped_sections(self) -> None:
        report = edit_report([label(caption_changed=True)], skipped={"unusable": ["x"]})
        data = json.loads(json.dumps(report.as_dict()))
        assert set(data) == {"overall", "by_event_type", "skipped"}
        assert data["overall"]["caption_edit_rate"] == 1.0
        assert data["by_event_type"]["intrusion"]["labels"] == 1
        assert data["skipped"] == {"unusable": 1}

    def test_unknown_rates_are_null(self) -> None:
        assert EditStats().as_dict()["caption_edit_rate"] is None


class TestMarkdown:
    def test_a_row_for_all_then_each_event_type_in_order(self) -> None:
        report = edit_report([label(event_type="running"), label(event_type="intrusion")])
        lines = render_markdown(report).splitlines()
        assert lines[0].startswith("| Event type |")
        assert [line.split("|")[1].strip() for line in lines[2:]] == ["all", "intrusion", "running"]

    def test_percentages_have_one_decimal(self) -> None:
        report = edit_report([label(caption_changed=True, similarity=0.5), label(), label()])
        row = render_markdown(report).splitlines()[2]
        assert "33.3%" in row  # caption edit rate 1/3
        assert "16.7%" in row  # mean rewrite (0.5 + 0 + 0) / 3

    def test_unknown_rates_say_n_a(self) -> None:
        assert "n/a" in render_markdown(edit_report([label(drafted=False)]))

    def test_skipped_are_listed_below(self) -> None:
        text = render_markdown(
            edit_report([label()], skipped={"unusable": ["a"], "incomplete": ["b", "c"]})
        )
        assert text.rstrip().splitlines()[-1] == "Skipped: 1 unusable, 2 incomplete"

    def test_nothing_skipped_adds_no_line(self) -> None:
        assert "Skipped" not in render_markdown(edit_report([label()]))

    def test_an_empty_report_still_renders(self) -> None:
        assert render_markdown(EditReport()).splitlines()[2].startswith("| all | 0 | 0 | n/a")
