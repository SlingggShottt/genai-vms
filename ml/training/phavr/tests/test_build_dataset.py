"""Unit tests for the PhaVR dataset builder, with small synthetic videos (one flat colour per
second). `uv run pytest ml/training/phavr/tests`."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from annotation_kit.phases import PHASES
from PIL import Image


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TRAINING = Path(__file__).resolve().parents[2]
bd = load("phavr_build_dataset", TRAINING / "phavr" / "build_dataset.py")
tg = load("tg_build_dataset_for_phavr", TRAINING / "tg" / "build_dataset.py")

PALETTE = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255),
    (255, 128, 0), (128, 0, 255), (0, 128, 128), (128, 128, 0), (255, 255, 255), (60, 60, 60),
]  # fmt: skip
SPANS = {
    "baseline": (0.0, 3.0), "precursor": (3.0, 6.0), "escalation": (6.0, 8.0),
    "action": (8.0, 10.0), "aftermath": (10.0, 12.0),
}  # fmt: skip
BANK = bd.load_vqa_bank(bd.REPO / "config" / "vqa_bank.yaml")


def make_video(path: Path, seconds: int = 12, fps: int = 5) -> None:
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 640, 480, "yuv420p"
        for i in range(seconds * fps):
            image = Image.new("RGB", (640, 480), PALETTE[(i // fps) % len(PALETTE)])
            for packet in stream.encode(av.VideoFrame.from_image(image)):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def nearest_second(path: Path) -> int:
    px = Image.open(path).convert("RGB").getpixel((10, 10))
    return min(
        range(len(PALETTE)),
        key=lambda k: sum((a - b) ** 2 for a, b in zip(PALETTE[k], px, strict=True)),
    )


def phase_line(clip: str, source: str, event_type: str = "intrusion") -> dict:
    return {
        "schema_version": "phase_labels.v1", "clip_id": clip, "source_video": source,
        "event_type": event_type, "primary_view": "cam01",
        "views": [
            {"camera": c, "video_uri": f"s3://vms-evidence/clips/{clip}/{c}.mp4"}
            for c in ("cam01", "cam02")
        ],
        "phases": [{"phase": p, "start_s": a, "end_s": b} for p, (a, b) in SPANS.items()],
    }  # fmt: skip


def phavr_line(
    clip: str, source: str, view: str, phase: str, event_type: str = "intrusion"
) -> dict:
    a, b = SPANS[phase]
    return {
        "schema_version": "phavr_label.v1", "clip_id": clip, "source_video": source,
        "event_type": event_type, "view": view, "phase": phase, "start_s": a, "end_s": b,
        "caption": f"A person is visible in the {phase} stage.",
        "vqa": [
            {"id": q.id, "q": q.text, "a": q.answers[0]} for q in BANK.questions_for(event_type)
        ],
        "pseudo": None, "edits": None, "annotator": "K",
    }  # fmt: skip


@pytest.fixture
def world(tmp_path: Path):
    videos = tmp_path / "evidence"
    phase_lines, phavr_lines = [], []
    for n in range(6):
        clip, src = f"clip{n}", f"src{n}"
        phase_lines.append(phase_line(clip, src))
        for cam in ("cam01", "cam02"):
            make_video(videos / "clips" / clip / f"{cam}.mp4")
            phavr_lines += [phavr_line(clip, src, cam, p) for p in PHASES]
    phase_labels, phavr = tmp_path / "phase_labels.jsonl", tmp_path / "phavr_labels.jsonl"
    phase_labels.write_text("".join(json.dumps(x) + "\n" for x in phase_lines))
    phavr.write_text("".join(json.dumps(x) + "\n" for x in phavr_lines))
    return {
        "tmp": tmp_path,
        "videos": videos,
        "phase": phase_labels,
        "phavr": phavr,
        "lines": phavr_lines,
    }


def run(world, out: Path, **kw) -> dict:
    return bd.build(world["phavr"], world["phase"], world["videos"], out, **kw)


def read(out: Path, split: str) -> list[dict]:
    return [json.loads(x) for x in (out / f"{split}.jsonl").read_text().splitlines()]


# ---- pieces -------------------------------------------------------------------------------------


def test_frames_come_from_inside_the_stage_first_and_last_included() -> None:
    assert bd.span_frame_times(8.0, 12.0, 3) == [8.0, 10.0, 12.0]
    assert bd.span_frame_times(8.0, 9.0, 4) == [
        8.0,
        8.5,
        9.0,
    ]  # fewer inside than asked: all of them
    assert bd.span_frame_times(3.2, 3.4, 2) == [3.5]  # none inside: the one nearest the middle
    assert bd.span_frame_times(3.0, 3.0, 2) == [3.0]


def test_answers_are_canonical_and_unanswered_questions_are_not_asked() -> None:
    questions = BANK.questions_for("intrusion")
    label = bd.PhavrLabel.model_validate(phavr_line("c", "s", "cam01", "action"))
    label.vqa[0].a = label.vqa[0].a.upper() + "."  # an annotator's capitals and full stop
    del label.vqa[1]  # nobody answered the second question
    asked, problems = bd.answers_for(label, questions)
    assert problems == []
    assert [q.id for q, _ in asked] == [q.id for q in questions if q.id != questions[1].id]
    assert asked[0][1] == questions[0].answers[0]  # back to the bank's own spelling


def test_an_answer_outside_the_vocabulary_is_a_problem_not_a_guess() -> None:
    questions = BANK.questions_for("intrusion")
    label = bd.PhavrLabel.model_validate(phavr_line("c", "s", "cam01", "action"))
    label.vqa[0].a = "Probably"
    asked, problems = bd.answers_for(label, questions)
    assert (
        len(asked) == len(questions) - 1
        and "Probably" in problems[0]
        and questions[0].id in problems[0]
    )


# ---- the prompt and the answer are the service's ------------------------------------------------


class _Footage:
    async def image(self, uri: str) -> bytes:
        return b"jpeg"


async def test_training_prompt_and_answer_match_what_the_service_sends_and_parses() -> None:
    from reasoning.adapters.footage import FootFrame
    from reasoning.adapters.store import EventInfo
    from reasoning.domain.context import build_context
    from reasoning.steps.readings import ViewDraft, clean_answers, read_view
    from vms_common.contracts.reasoning import PhaseSpan
    from vms_common.llm.testing import FakeGateway

    t0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    event = EventInfo(
        id="e1", camera_id="cam02", event_type="intrusion", severity="high",
        rule_id="intrusion.restricted",
        zone_name=None, start=t0 + timedelta(seconds=10), end=t0 + timedelta(seconds=16),
        status="verified", caption=None, confidence=0.9,
    )  # fmt: skip
    ctx = build_context([event], group_id=None, pad_before_s=10, pad_after_s=10, max_views=2)
    frames = [FootFrame("cam02", t0 + timedelta(seconds=k / 2), f"u{k}") for k in range(53)]
    span = PhaseSpan(
        phase="action", start=t0 + timedelta(seconds=8), end=t0 + timedelta(seconds=12), source="x"
    )
    questions = list(BANK.questions_for("intrusion"))
    gateway = FakeGateway({"phase_vr": {"caption": "ok", "answers": []}})
    await read_view(gateway, _Footage(), ctx, span, "cam02", frames, questions, n_frames=3)
    service_prompt = gateway.calls[0].prompt

    line = phavr_line("c", "s", "cam02", "action")
    label = bd.PhavrLabel.model_validate(line)
    times = bd.span_frame_times(8.0, 12.0, 3)
    assert bd.render_user_prompt(label, times, questions) == service_prompt

    # the answer the adapter is taught parses with the service's own model and survives its cleaning
    asked, _ = bd.answers_for(label, tuple(questions))
    record = bd.sample_record(label, "train", times, asked, ["a", "b", "c"])
    draft = ViewDraft.model_validate_json(record["messages"][1]["content"][0]["text"])
    cleaned = clean_answers(draft, questions)
    assert [(i, v) for i, _, v in cleaned] == [(q.id, a) for q, a in asked]
    assert draft.caption == label.caption


# ---- end to end ---------------------------------------------------------------------------------


def test_build_makes_samples_per_label_with_the_right_frames_and_no_split_leaks(world) -> None:
    out = world["tmp"] / "ds"
    manifest = run(world, out)
    samples = [s for name in bd.SPLITS for s in read(out, name)]
    assert len(samples) == 6 * 2 * 5  # clips x views x stages
    by_video: dict[str, set[str]] = {}
    for s in samples:
        by_video.setdefault(s["source_video"], set()).add(s["split"])
        assert 2 <= len(s["images"]) <= 4 and len(s["images"]) == len(s["frame_times"])
        assert [c["type"] for c in s["messages"][0]["content"]].count("image") == len(s["images"])
        lo, hi = SPANS[s["phase"]]
        assert all(lo <= t <= hi for t in s["frame_times"])
        for rel, t in zip(s["images"], s["frame_times"], strict=True):
            assert nearest_second(out / rel) == min(
                int(t), 11
            )  # the frame shown at t s is the one at t s
            assert Image.open(out / rel).height <= 360
    assert all(len(v) == 1 for v in by_video.values())
    assert manifest["counts"]["samples"] == {n: len(read(out, n)) for n in bd.SPLITS}
    assert manifest["counts"]["phases"] == dict.fromkeys(sorted(PHASES), 12)
    for name, digest in manifest["files"].items():
        assert bd.sha256_file(out / name) == digest
    assert manifest["vqa_bank_sha256"] == bd.sha256_file(bd.REPO / "config" / "vqa_bank.yaml")


def test_both_builders_share_one_split_file_and_neither_disturbs_the_other(world) -> None:
    shared = world["tmp"] / "splits.json"
    tg_out = world["tmp"] / "tg"
    tg.build(world["phase"], world["videos"], tg_out, splits_path=shared)
    first = json.loads(shared.read_text())["assignments"]
    manifest = run(world, world["tmp"] / "phavr", splits_path=shared)
    assert (
        json.loads(shared.read_text())["assignments"] == first
    )  # PhaVR joined the TG split, moved nothing
    for split, videos in manifest["splits"].items():
        assert all(first[v] == split for v in videos)


def test_an_existing_split_file_is_honoured_even_when_the_hash_would_choose_otherwise(
    world,
) -> None:
    shared = world["tmp"] / "splits.json"
    natural = bd.assign_splits([f"src{n}" for n in range(6)], {}, (0.7, 0.15, 0.15), seed=7)
    rotate = {"train": "val", "val": "test", "test": "train"}
    forced = {v: rotate[s] for v, s in natural.items()}  # what no seed would produce
    shared.write_text(
        json.dumps({"seed": 99, "fractions": [0.7, 0.15, 0.15], "assignments": forced})
    )
    out = world["tmp"] / "ds"
    manifest = run(world, out, splits_path=shared)
    for split, videos in manifest["splits"].items():
        assert all(forced[v] == split for v in videos)
    assert all(forced[s["source_video"]] == s["split"] for n in bd.SPLITS for s in read(out, n))
    assert json.loads(shared.read_text())["assignments"] == forced  # and it is not rewritten


def test_unusable_labels_are_skipped_and_listed_not_fatal(world) -> None:
    lines = [dict(x) for x in world["lines"]]
    lines[0]["caption"] = "  "  # empty caption
    lines[1]["vqa"] = [{**lines[1]["vqa"][0], "a": "Probably"}, *lines[1]["vqa"][1:]]  # vocabulary
    lines[2]["view"] = "cam09"  # a view the phase labels do not have
    world["phavr"].write_text("".join(json.dumps(x) + "\n" for x in lines))
    (world["videos"] / "clips" / "clip5" / "cam02.mp4").unlink()
    manifest = run(world, world["tmp"] / "ds")
    reasons = " | ".join(manifest["skipped"])
    assert "empty caption" in reasons and "Probably" in reasons
    assert "no such view" in reasons and "video not found" in reasons
    assert sum(manifest["counts"]["samples"].values()) == 60 - 3 - 5


def test_bad_label_lines_are_all_reported_together(world) -> None:
    with world["phavr"].open("a") as f:
        f.write(json.dumps(world["lines"][0]) + "\n")  # the same label twice
        f.write(json.dumps({**world["lines"][1], "phase": "nonsense"}) + "\n")
    with pytest.raises(bd.LabelError) as exc:
        run(world, world["tmp"] / "ds")
    assert "appears 2 times" in str(exc.value) and "line 62" in str(exc.value)


def test_the_build_is_reproducible_and_the_frame_limits_are_the_services(world) -> None:
    a = run(world, world["tmp"] / "a")
    b = run(world, world["tmp"] / "b")
    assert a["files"] == b["files"] and a["frames_sha256"] == b["frames_sha256"]
    for lo, hi in ((0, 3), (2, 5), (4, 3)):
        with pytest.raises(ValueError):
            run(world, world["tmp"] / "x", frames_min=lo, frames_max=hi)
