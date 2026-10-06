"""TG dataset builder (P5-D1): phase-annotated clips -> instruction data for the TG adapter.

    uv run python ml/training/tg/build_dataset.py \
        --labels phase_labels.jsonl --videos-root /path/to/evidence --out datasets/tg-v1

Reads `phase_labels.jsonl` (`phase_labels.v1`, written by the annotation kit). For every clip and
every camera view it samples a handful of frames, renders the prompt EXACTLY as the reasoning
service does at inference (the `phase_tg` prompt, the same claim text, the same frame picker, the
same relative-seconds timestamps) and writes the answer the model should give: one stage name per
frame. An adapter trained on this is a drop-in replacement for the zero-shot model in
`services/reasoning/steps/phases.py`. The design's span-style answer (design §8.3) is not what the
service parses today, so it is not what is trained.

Output (all paths relative to `--out`):

    train.jsonl / val.jsonl / test.jsonl   one chat-format sample per (clip, camera)
    frames/<clip_id>/<camera>/NN.jpg        <= 360 px high
    manifest.json                           config, prompt hash, splits, counts, file hashes
    dataset-metadata.json                   for `kaggle datasets create` (edit the id first)

Splits are by SOURCE VIDEO, never by clip: clips cut from one video share a scene. The
assignment is stored in `--splits` (default `<out>/splits.json`) and only ever extended, so adding
annotations later cannot move a video from train to test; the PhaVR builder (P5-J1) reads the
same file.

What the detector would have flagged is not in the labels, so the "flagged incident span" shown in
the prompt is the annotated `action` phase moved by up to `--jitter` seconds at each end, seeded per
sample, because the real detector's timing is rarely exact.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for `dataset_common`

from annotation_kit.schema import PhaseLabelClip  # noqa: E402
from dataset_common import (  # noqa: E402
    MAX_HEIGHT,
    SPLITS,
    LabelError,
    assign_splits,
    clear_outputs,
    extract_frames,
    frames_digest,
    read_splits,
    resolve_video,
    sha256_file,
    sha256_text,
    target_counts,
    write_kaggle_metadata,
    write_split_files,
    write_splits,
)
from pydantic import ValidationError  # noqa: E402
from reasoning.domain.context import CLAIMS  # noqa: E402
from reasoning.domain.sampling import pick_evenly  # noqa: E402
from vms_common.llm import render_prompt  # noqa: E402
from vms_common.llm.prompts import PROMPTS_DIR  # noqa: E402

__all__ = ["MAX_HEIGHT", "SPLITS", "assign_splits", "target_counts"]  # re-exported for the tests

PROMPT_NAME = "phase_tg"
PROMPT_VERSION = "1.0"
# Footage frames are perception's sampled frames: 2 a second normally, 1 when it falls behind
# (`default_sample_fps` / `degraded_sample_fps`). The service picks among whatever exists.
FRAME_FPS = 2.0
MIN_FRAMES = 3  # below this the service skips the model and uses the detector's timing


def load_clips(path: Path) -> list[PhaseLabelClip]:
    clips, problems = [], []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            clips.append(PhaseLabelClip.model_validate_json(line))
        except ValidationError as exc:
            problems.append(f"line {n}: {exc.errors()[0]['msg']}")
        except ValueError as exc:
            problems.append(f"line {n}: {exc}")
    ids = Counter(c.clip_id for c in clips)
    problems += [f"clip_id {i!r} appears {n} times" for i, n in ids.items() if n > 1]
    if problems:
        raise LabelError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    if not clips:
        raise LabelError(f"{path}: no clips")
    return clips


# ---- one sample ---------------------------------------------------------------------------------


def clip_duration(clip: PhaseLabelClip) -> float:
    return max(span.end_s for span in clip.phases)


def frame_times(duration_s: float, n: int, fps: float = FRAME_FPS) -> list[float]:
    """Where to look: the frames a camera has (`fps` a second), spread as the service does."""
    available = [k / fps for k in range(math.ceil(duration_s * fps))]
    return pick_evenly(available, n)


def label_frames(times: list[float], clip: PhaseLabelClip) -> tuple[list[str], int]:
    """The stage each frame shows, and how many frames fell outside every annotated span.

    A frame inside a span takes its stage. One in a gap, or after the last span, takes the stage
    before it; one before the first span takes the first stage. Labels never go backwards."""
    labels, outside = [], 0
    for t in times:
        label = clip.phases[0].phase
        inside = False
        for span in clip.phases:
            if span.start_s <= t < span.end_s:
                label, inside = span.phase, True
                break
            if t >= span.end_s:
                label = span.phase
        outside += not inside
        labels.append(label)
    return labels, outside


def flagged_span(clip: PhaseLabelClip, rng: random.Random, jitter_s: float) -> tuple[float, float]:
    """Stand-in for the detector's span: the `action` phase (else the middle phase), nudged."""
    duration = clip_duration(clip)
    by_phase = {span.phase: span for span in clip.phases}
    core = by_phase.get("action") or clip.phases[len(clip.phases) // 2]
    start = min(max(core.start_s + rng.uniform(-jitter_s, jitter_s), 0.0), duration)
    end = min(max(core.end_s + rng.uniform(-jitter_s, jitter_s), 0.0), duration)
    if end <= start:
        start, end = core.start_s, core.end_s
    return round(start, 1), round(end, 1)


def claim_for(event_type: str) -> str:
    """What the service says was flagged (`Context.claim`, here without a zone)."""
    return CLAIMS.get(event_type, f"a {event_type.replace('_', ' ')} is happening")


def render_user_prompt(
    clip: PhaseLabelClip, camera: str, times: list[float], span: tuple[float, float]
) -> str:
    return render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        event_type=clip.event_type.replace("_", " "),
        claim=claim_for(clip.event_type),
        camera=camera,
        frames=[{"at": round(t, 1)} for t in times],
        event_start=span[0],
        event_end=span[1],
    )


def sample_record(
    clip: PhaseLabelClip,
    camera: str,
    split: str,
    times: list[float],
    labels: list[str],
    span: tuple[float, float],
    images: list[str],
) -> dict:
    prompt = render_user_prompt(clip, camera, times, span)
    return {
        "id": f"{clip.clip_id}|{camera}",
        "clip_id": clip.clip_id,
        "source_video": clip.source_video,
        "split": split,
        "camera": camera,
        "event_type": clip.event_type,
        "images": images,
        "frame_times": [round(t, 1) for t in times],
        "labels": labels,
        "flagged_span": list(span),
        "window_s": clip_duration(clip),
        "n_views": len(clip.views),
        "phases": [
            {"phase": s.phase, "start_s": s.start_s, "end_s": s.end_s} for s in clip.phases
        ],  # the annotated truth, for the evaluation (P5-D3)
        "messages": [
            {
                "role": "user",
                "content": [
                    *({"type": "image", "image": path} for path in images),
                    {"type": "text", "text": prompt},
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": json.dumps({"phases": labels})}],
            },
        ],
    }


# ---- the build ----------------------------------------------------------------------------------


def build(
    labels_path: Path,
    videos_root: Path,
    out: Path,
    *,
    splits_path: Path | None = None,
    fractions: tuple[float, float, float] = (0.7, 0.15, 0.15),
    frames_min: int = 5,
    frames_max: int = 8,
    jitter_s: float = 1.5,
    frame_fps: float = FRAME_FPS,
    seed: int = 7,
) -> dict:
    if not MIN_FRAMES <= frames_min <= frames_max <= 8:
        raise ValueError(
            "frames must satisfy 3 <= frames_min <= frames_max <= 8 (the service's cap)"
        )
    clips = load_clips(labels_path)
    splits_path = splits_path or out / "splits.json"
    videos = sorted({c.source_video for c in clips})
    assignment = assign_splits(videos, read_splits(splits_path), fractions, seed)
    if len(videos) < 3:
        print(
            f"WARNING: only {len(videos)} source video(s); everything goes to train",
            file=sys.stderr,
        )

    clear_outputs(out)

    rows: dict[str, list[dict]] = {s: [] for s in SPLITS}
    stats = Counter()
    skipped: list[str] = []
    for clip in sorted(clips, key=lambda c: c.clip_id):
        split = assignment[clip.source_video]
        for view in clip.views:
            seed_for_sample = int(sha256_text(f"{seed}|{clip.clip_id}|{view.camera}")[:16], 16)
            rng = random.Random(seed_for_sample)  # noqa: S311 - sampling, not security
            n = rng.randint(frames_min, frames_max)
            times = frame_times(clip_duration(clip), n, frame_fps)
            if len(times) < MIN_FRAMES:
                skipped.append(
                    f"{clip.clip_id}|{view.camera}: clip too short for {MIN_FRAMES} frames"
                )
                continue
            video = resolve_video(view.video_uri, videos_root)
            if not video.is_file():
                skipped.append(f"{clip.clip_id}|{view.camera}: video not found at {video}")
                continue
            frame_dir = out / "frames" / clip.clip_id / view.camera
            paths = extract_frames(video, times, frame_dir)
            labels, outside = label_frames(times, clip)
            span = flagged_span(clip, rng, jitter_s)
            images = [str(p.relative_to(out)) for p in paths]
            rows[split].append(sample_record(clip, view.camera, split, times, labels, span, images))
            stats["samples"] += 1
            stats["frames"] += len(times)
            stats["frames_outside_every_span"] += outside
    if not stats["samples"]:
        raise LabelError("no sample could be built:\n  " + "\n  ".join(skipped))

    files = write_split_files(out, rows)
    label_counts = Counter(label for items in rows.values() for r in items for label in r["labels"])
    write_splits(splits_path, assignment, fractions, seed)
    prompt_file = PROMPTS_DIR / PROMPT_NAME / f"{PROMPT_VERSION}.md"
    manifest = {
        "schema": "tg_dataset.v1",
        "builder": "ml/training/tg/build_dataset.py",
        "prompt": {
            "name": PROMPT_NAME,
            "version": PROMPT_VERSION,
            "sha256": sha256_file(prompt_file),
        },
        "config": {
            "frames_min": frames_min,
            "frames_max": frames_max,
            "max_height": MAX_HEIGHT,
            "jitter_s": jitter_s,
            "frame_fps": frame_fps,
            "seed": seed,
            "fractions": list(fractions),
        },
        "source_labels_sha256": sha256_file(labels_path),
        "counts": {
            "clips": len(clips),
            "source_videos": len(videos),
            "samples": {s: len(rows[s]) for s in SPLITS},
            "frames": stats["frames"],
            "frames_outside_every_span": stats["frames_outside_every_span"],
            "labels": dict(sorted(label_counts.items())),
        },
        "splits": {s: sorted(v for v in videos if assignment[v] == s) for s in SPLITS},
        "files": files,
        "frames_sha256": frames_digest(out),
        "skipped": skipped,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    write_kaggle_metadata(out, "GenAI-VMS TG phase grounding", "genai-vms-tg-phase")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", type=Path, required=True, help="phase_labels.jsonl")
    ap.add_argument(
        "--videos-root",
        type=Path,
        required=True,
        help="where s3://<bucket>/<key> videos live as <key>",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--splits",
        type=Path,
        default=None,
        help="shared split assignment (default <out>/splits.json)",
    )
    ap.add_argument("--frames-min", type=int, default=5)
    ap.add_argument("--frames-max", type=int, default=8)
    ap.add_argument(
        "--jitter",
        type=float,
        default=1.5,
        help="seconds the flagged span may differ from `action`",
    )
    ap.add_argument(
        "--frame-fps",
        type=float,
        default=FRAME_FPS,
        help="frames a second the footage has (perception: 2, or 1 when behind)",
    )
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    try:
        manifest = build(
            args.labels,
            args.videos_root,
            args.out,
            splits_path=args.splits,
            frames_min=args.frames_min,
            frames_max=args.frames_max,
            jitter_s=args.jitter,
            frame_fps=args.frame_fps,
            seed=args.seed,
        )
    except LabelError as exc:
        sys.exit(str(exc))
    c = manifest["counts"]
    print(f"{c['samples']} samples from {c['clips']} clips / {c['source_videos']} source videos")
    print(f"{c['frames']} frames")
    print(f"labels: {c['labels']}")
    for line in manifest["skipped"]:
        print(f"skipped {line}")


if __name__ == "__main__":
    main()
