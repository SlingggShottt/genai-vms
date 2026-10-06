"""Unit tests for the TG dataset builder. They make small synthetic videos (one flat colour per
second) so that "the right frame at the right time" can be checked by colour. `make test` collects
`ml/`; one test at a time: `uv run pytest ml/training/tg/tests`."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from annotation_kit.phases import PHASES
from PIL import Image

SPEC = importlib.util.spec_from_file_location(
    "tg_build_dataset", Path(__file__).parent.parent / "build_dataset.py"
)
assert SPEC and SPEC.loader
bd = importlib.util.module_from_spec(SPEC)
sys.modules["tg_build_dataset"] = bd  # a dataclass or pydantic model looks its module up here
SPEC.loader.exec_module(bd)

PALETTE = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255),
    (255, 128, 0), (128, 0, 255), (0, 128, 128), (128, 128, 0), (255, 255, 255), (60, 60, 60),
    (200, 100, 100),
]  # fmt: skip
PHASES_12S = [
    ("baseline", 0.0, 3.0),
    ("precursor", 3.0, 6.0),
    ("escalation", 6.0, 8.0),
    ("action", 8.0, 10.0),
    ("aftermath", 10.0, 12.0),
]


def make_video(path: Path, seconds: int, fps: int = 5, size: tuple[int, int] = (640, 480)) -> None:
    """One flat colour per second: second k is PALETTE[k]."""
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        for i in range(seconds * fps):
            image = Image.new("RGB", size, PALETTE[(i // fps) % len(PALETTE)])
            for packet in stream.encode(av.VideoFrame.from_image(image)):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def nearest_second(path: Path) -> int:
    """Which second's colour the picture is."""
    r, g, b = Image.open(path).convert("RGB").getpixel((10, 10))
    return min(
        range(len(PALETTE)),
        key=lambda k: sum((a - c) ** 2 for a, c in zip(PALETTE[k], (r, g, b), strict=True)),
    )


def label_line(
    clip_id: str, source: str, cams=("cam01", "cam02"), event_type: str = "intrusion"
) -> dict:
    return {
        "schema_version": "phase_labels.v1",
        "clip_id": clip_id,
        "source_video": source,
        "event_type": event_type,
        "primary_view": cams[0],
        "views": [
            {"camera": c, "video_uri": f"s3://vms-evidence/clips/{clip_id}/{c}.mp4"} for c in cams
        ],
        "phases": [{"phase": p, "start_s": a, "end_s": b} for p, a, b in PHASES_12S],
        "annotator": "K",
    }


@pytest.fixture
def world(tmp_path: Path):
    """Six source videos with one 12 s clip and two camera views each, on disk."""
    videos = tmp_path / "evidence"
    lines = []
    for n in range(6):
        clip = f"clip{n}"
        lines.append(label_line(clip, f"src{n}"))
        for cam in ("cam01", "cam02"):
            make_video(videos / "clips" / clip / f"{cam}.mp4", 12)
    labels = tmp_path / "phase_labels.jsonl"
    labels.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return {"tmp": tmp_path, "videos": videos, "labels": labels, "lines": lines}


# ---- splits -------------------------------------------------------------------------------------


def test_target_counts_give_val_and_test_a_video_each_from_three_up() -> None:
    f = (0.7, 0.15, 0.15)
    assert bd.target_counts(2, f) == {"train": 2, "val": 0, "test": 0}
    assert bd.target_counts(3, f) == {"train": 1, "val": 1, "test": 1}
    assert bd.target_counts(10, f) == {"train": 6, "val": 2, "test": 2}  # 1.5 rounds to 2
    assert bd.target_counts(40, f) == {"train": 28, "val": 6, "test": 6}


def test_assignment_is_deterministic_whatever_the_order_and_hits_the_targets() -> None:
    videos = [f"v{i:02d}" for i in range(20)]
    a = bd.assign_splits(videos, {}, (0.7, 0.15, 0.15), seed=3)
    b = bd.assign_splits(list(reversed(videos)), {}, (0.7, 0.15, 0.15), seed=3)
    assert a == b
    counts = {s: sum(1 for v in a.values() if v == s) for s in bd.SPLITS}
    assert counts == bd.target_counts(20, (0.7, 0.15, 0.15))
    assert bd.assign_splits(videos, {}, (0.7, 0.15, 0.15), seed=4) != a  # the seed matters


def test_adding_videos_never_moves_an_assigned_one() -> None:
    first = bd.assign_splits([f"v{i}" for i in range(10)], {}, (0.7, 0.15, 0.15), seed=1)
    more = bd.assign_splits([f"v{i}" for i in range(16)], first, (0.7, 0.15, 0.15), seed=1)
    assert {v: s for v, s in more.items() if v in first} == first
    assert len(more) == 16


# ---- frames and labels --------------------------------------------------------------------------


def test_frame_times_are_whole_seconds_inside_the_clip_spread_first_to_last() -> None:
    assert bd.frame_times(26.0, 5) == [
        0.0,
        6.0,
        12.0,
        19.0,
        25.0,
    ]  # a video of 26 s has no frame at 26
    assert bd.frame_times(26.5, 3) == [0.0, 13.0, 26.0]  # but one of 26.5 s does
    assert bd.frame_times(2.0, 5) == [0.0, 1.0]  # a short clip gives what it has


def test_labels_follow_the_spans_and_never_go_backwards() -> None:
    clip = bd.PhaseLabelClip.model_validate(label_line("c", "s"))
    labels, outside = bd.label_frames([0, 2.9, 3, 5.9, 6, 7.9, 8, 10, 11.9], clip)
    assert labels == [
        "baseline", "baseline", "precursor", "precursor", "escalation", "escalation",
        "action", "aftermath", "aftermath",
    ]  # fmt: skip
    assert outside == 0
    rank = [PHASES.index(x) for x in labels]
    assert rank == sorted(rank)


def test_a_frame_in_a_gap_or_past_the_end_takes_the_stage_before_it() -> None:
    line = label_line("c", "s")
    line["phases"] = [
        {"phase": "precursor", "start_s": 2.0, "end_s": 4.0},
        {"phase": "action", "start_s": 6.0, "end_s": 8.0},
    ]
    clip = bd.PhaseLabelClip.model_validate(line)
    labels, outside = bd.label_frames([0.0, 3.0, 5.0, 7.0, 9.0], clip)
    assert labels == ["precursor", "precursor", "precursor", "action", "action"]
    assert outside == 3  # 0.0 (before), 5.0 (gap), 9.0 (after)


def test_the_flagged_span_is_the_action_phase_moved_a_little_and_stays_in_the_clip() -> None:
    import random

    clip = bd.PhaseLabelClip.model_validate(label_line("c", "s"))
    for seed in range(50):
        start, end = bd.flagged_span(clip, random.Random(seed), 1.5)  # noqa: S311 - a seeded test RNG
        assert 6.5 <= start <= 9.5 and 8.5 <= end <= 11.5 and 0 <= start < end <= 12
    assert bd.flagged_span(clip, random.Random(1), 0.0) == (8.0, 10.0)  # noqa: S311


# ---- the prompt is the one the service sends ----------------------------------------------------


class _Footage:
    async def image(self, uri: str) -> bytes:
        return b"jpeg"


async def test_training_prompt_is_byte_for_byte_what_the_service_sends() -> None:
    from reasoning.adapters.footage import FootFrame
    from reasoning.adapters.store import EventInfo
    from reasoning.domain.context import build_context
    from reasoning.domain.timeline import FrameLabels
    from reasoning.steps.phases import locate_phases
    from vms_common.llm.testing import FakeGateway

    t0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    event = EventInfo(
        id="e1", camera_id="cam02", event_type="abandoned_object", severity="high",
        rule_id="abandoned_object", zone_name=None, start=t0 + timedelta(seconds=10),
        end=t0 + timedelta(seconds=16), status="verified", caption=None, confidence=0.9,
    )  # fmt: skip
    ctx = build_context([event], group_id=None, pad_before_s=10, pad_after_s=10, max_views=2)
    frames = [FootFrame("cam02", t0 + timedelta(seconds=k), f"u{k}") for k in range(27)]
    gateway = FakeGateway(
        {"phase_tg": {"phases": ["baseline", "baseline", "action", "aftermath", "aftermath"]}}
    )
    await locate_phases(gateway, _Footage(), ctx, frames, n_frames=5)
    service_prompt = gateway.calls[0].prompt
    assert len(gateway.calls[0].images) == 5

    line = label_line("c", "s", event_type="abandoned_object")
    line["phases"] = [{"phase": "baseline", "start_s": 0.0, "end_s": 26.0}]
    clip = bd.PhaseLabelClip.model_validate(line)
    times = [0.0, 6.0, 13.0, 20.0, 26.0]  # what the service picked from the 27 frames above
    mine = bd.render_user_prompt(clip, "cam02", times, (10.0, 16.0))
    assert mine == service_prompt

    # and the answer the adapter is taught parses with the service's own response model
    record = bd.sample_record(
        clip, "cam02", "train", times, ["baseline"] * 5, (10.0, 16.0), ["a"] * 5
    )
    answer = record["messages"][1]["content"][0]["text"]
    assert FrameLabels.model_validate_json(answer).phases == ["baseline"] * 5


def test_claims_come_from_the_service_table_with_the_same_fallback() -> None:
    assert bd.claim_for("intrusion") == "a person is inside an area they should not be in"
    assert bd.claim_for("theft") == "a theft is happening"
    assert bd.claim_for("abandoned_object") == bd.CLAIMS["abandoned_object"]


# ---- end to end ---------------------------------------------------------------------------------


def run_build(world, out: Path, **kw) -> dict:
    return bd.build(world["labels"], world["videos"], out, **kw)


def read_split(out: Path, name: str) -> list[dict]:
    return [json.loads(x) for x in (out / f"{name}.jsonl").read_text().splitlines()]


def test_build_makes_consistent_samples_and_never_splits_a_source_video(world) -> None:
    out = world["tmp"] / "ds"
    manifest = run_build(world, out)
    samples = [s for name in bd.SPLITS for s in read_split(out, name)]
    assert len(samples) == 12  # 6 clips x 2 cameras
    assert manifest["counts"]["samples"] == {n: len(read_split(out, n)) for n in bd.SPLITS}
    by_video: dict[str, set[str]] = {}
    for s in samples:
        by_video.setdefault(s["source_video"], set()).add(s["split"])
        assert (
            s["split"] in manifest["splits"] and s["source_video"] in manifest["splits"][s["split"]]
        )
    assert all(len(v) == 1 for v in by_video.values())  # no source video in two splits
    assert {len(read_split(out, n)) for n in ("val", "test")} == {2}  # one video x two cameras each

    for s in samples:
        n = len(s["images"])
        assert bd.MIN_FRAMES <= n <= 8 and len(s["labels"]) == n == len(s["frame_times"])
        ranks = [PHASES.index(x) for x in s["labels"]]
        assert ranks == sorted(ranks)
        user, assistant = s["messages"]
        assert [c["type"] for c in user["content"]].count("image") == n
        assert json.loads(assistant["content"][0]["text"]) == {"phases": s["labels"]}
        for rel, t in zip(s["images"], s["frame_times"], strict=True):
            path = out / rel
            assert Image.open(path).height <= bd.MAX_HEIGHT
            assert nearest_second(path) == int(t)  # the frame shown at "t s" is the one at t s


def test_the_manifest_hashes_match_the_files_and_the_build_is_reproducible(world) -> None:
    a = run_build(world, world["tmp"] / "a")
    b = run_build(world, world["tmp"] / "b")
    for name, digest in a["files"].items():
        assert bd.sha256_file(world["tmp"] / "a" / name) == digest
    assert a["files"] == b["files"] and a["frames_sha256"] == b["frames_sha256"]
    assert a["prompt"]["sha256"] == bd.sha256_file(bd.PROMPTS_DIR / "phase_tg" / "1.0.md")
    assert a["source_labels_sha256"] == bd.sha256_file(world["labels"])
    assert run_build(world, world["tmp"] / "c", seed=8)["files"] != a["files"]  # the seed matters


def test_adding_clips_later_keeps_every_earlier_split(world) -> None:
    out = world["tmp"] / "ds"
    first_lines = world["lines"][:4]
    world["labels"].write_text("".join(json.dumps(x) + "\n" for x in first_lines))
    first = run_build(world, out)["splits"]
    world["labels"].write_text("".join(json.dumps(x) + "\n" for x in world["lines"]))
    second = run_build(world, out)["splits"]
    for split, videos in first.items():
        assert set(videos) <= set(second[split])  # nobody moved
    assert sum(len(v) for v in second.values()) == 6


def test_a_missing_video_is_skipped_and_reported_not_fatal(world) -> None:
    (world["videos"] / "clips" / "clip0" / "cam02.mp4").unlink()
    manifest = run_build(world, world["tmp"] / "ds")
    assert sum(manifest["counts"]["samples"].values()) == 11
    assert any("clip0|cam02" in line and "not found" in line for line in manifest["skipped"])


def test_bad_labels_are_all_reported_together(world) -> None:
    bad = label_line("clip1", "src1")  # a second clip1
    broken = label_line("clipX", "srcX")
    broken["phases"] = [{"phase": "action", "start_s": 5.0, "end_s": 4.0}]
    with world["labels"].open("a") as f:
        f.write(json.dumps(bad) + "\n" + json.dumps(broken) + "\n")
    with pytest.raises(bd.LabelError) as exc:
        run_build(world, world["tmp"] / "ds")
    message = str(exc.value)
    assert "clip_id 'clip1' appears 2 times" in message
    assert "line 8" in message and "end_s" in message


def test_frame_count_limits_follow_the_services_cap(world) -> None:
    for lo, hi in ((2, 5), (5, 9), (6, 5)):
        with pytest.raises(ValueError):
            run_build(world, world["tmp"] / "x", frames_min=lo, frames_max=hi)


def test_a_short_video_still_gives_its_last_frame_for_times_it_cannot_reach(world) -> None:
    make_video(world["videos"] / "clips" / "clip0" / "cam01.mp4", 8)  # the labels say 12 s
    out = world["tmp"] / "ds"
    run_build(world, out)
    sample = next(s for n in bd.SPLITS for s in read_split(out, n) if s["id"] == "clip0|cam01")
    last_colours = {nearest_second(out / rel) for rel in sample["images"][-2:]}
    assert last_colours <= {7}  # the final second of an 8 s video
