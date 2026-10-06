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
import hashlib
import json
import math
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

from annotation_kit.schema import PhaseLabelClip
from pydantic import ValidationError
from reasoning.domain.context import CLAIMS
from reasoning.domain.sampling import pick_evenly
from vms_common.llm import render_prompt
from vms_common.llm.prompts import PROMPTS_DIR

PROMPT_NAME = "phase_tg"
PROMPT_VERSION = "1.0"
SPLITS = ("train", "val", "test")
MAX_HEIGHT = 360
KEYFRAME_FPS = (
    1.0  # footage frames exist once a second (ingestion's keyframe_fps), so pick among those
)
MIN_FRAMES = 3  # below this the service skips the model and uses the detector's timing


class LabelError(Exception):
    """The labels file is unusable; the message lists every problem found."""


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


# ---- splits -------------------------------------------------------------------------------------


def target_counts(n: int, fractions: tuple[float, float, float]) -> dict[str, int]:
    """How many of `n` source videos go to each split. Val and test get at least one once there are
    three videos; below that everything trains (a split of one video says nothing)."""
    if n < 3:
        return {"train": n, "val": 0, "test": 0}
    val = max(1, round(fractions[1] * n))
    test = max(1, round(fractions[2] * n))
    return {"train": n - val - test, "val": val, "test": test}


def assign_splits(
    videos: list[str],
    existing: dict[str, str],
    fractions: tuple[float, float, float],
    seed: int,
) -> dict[str, str]:
    """`existing` assignments are kept; new videos fill what each split still lacks. Deterministic:
    new videos are taken in the order of a seeded hash, not the order they appear in the file."""
    assignment = {v: s for v, s in existing.items() if v in set(videos)}
    new = sorted((v for v in videos if v not in assignment), key=lambda v: _h(f"{seed}|{v}"))
    want = target_counts(len(videos), fractions)
    have = Counter(assignment.values())
    for v in new:
        # the split furthest below its target; ties go train, val, test
        split = max(SPLITS, key=lambda s: (want[s] - have[s], -SPLITS.index(s)))
        assignment[v] = split
        have[split] += 1
    return assignment


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---- one sample ---------------------------------------------------------------------------------


def clip_duration(clip: PhaseLabelClip) -> float:
    return max(span.end_s for span in clip.phases)


def frame_times(duration_s: float, n: int) -> list[float]:
    """Where to look: the frames a camera has (one a second), spread evenly as the service does."""
    available = [k / KEYFRAME_FPS for k in range(math.ceil(duration_s * KEYFRAME_FPS))]
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


# ---- frames -------------------------------------------------------------------------------------


def resolve_video(uri: str, videos_root: Path) -> Path:
    """`s3://bucket/key` -> `<videos_root>/key`; `file://` and plain paths are used as given."""
    if uri.startswith("s3://"):
        return videos_root / uri.split("/", 3)[3]
    if uri.startswith("file://"):
        return Path(uri[len("file://") :])
    path = Path(uri)
    return path if path.is_absolute() else videos_root / path


def extract_frames(video: Path, times: list[float], out_dir: Path) -> list[Path]:
    """The frame at (or just after) each time, shrunk to at most `MAX_HEIGHT` high, as JPEGs. A
    video that ends early gives its last frame for the times it cannot reach."""
    import av

    out_dir.mkdir(parents=True, exist_ok=True)
    targets = sorted(range(len(times)), key=lambda i: times[i])
    picked: dict[int, object] = {}
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        want = iter(targets)
        current = next(want, None)
        last = None
        for frame in container.decode(stream):
            last = frame
            t = float(frame.time) if frame.time is not None else 0.0
            while current is not None and t + 1e-3 >= times[current]:
                picked[current] = frame.to_image()
                current = next(want, None)
            if current is None:
                break
        while current is not None and last is not None:  # the video ended before this time
            picked[current] = last.to_image()
            current = next(want, None)
    paths = []
    for i in range(len(times)):
        if i not in picked:
            raise ValueError(f"{video}: no frames could be decoded")
        image = picked[i]
        if image.height > MAX_HEIGHT:
            width = max(1, round(image.width * MAX_HEIGHT / image.height))
            image = image.resize((width, MAX_HEIGHT))
        path = out_dir / f"{i:02d}.jpg"
        image.save(path, quality=85)
        paths.append(path)
    return paths


# ---- the build ----------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    seed: int = 7,
) -> dict:
    if not MIN_FRAMES <= frames_min <= frames_max <= 8:
        raise ValueError(
            "frames must satisfy 3 <= frames_min <= frames_max <= 8 (the service's cap)"
        )
    clips = load_clips(labels_path)
    splits_path = splits_path or out / "splits.json"
    existing = json.loads(splits_path.read_text())["assignments"] if splits_path.exists() else {}
    videos = sorted({c.source_video for c in clips})
    assignment = assign_splits(videos, existing, fractions, seed)
    if len(videos) < 3:
        print(
            f"WARNING: only {len(videos)} source video(s); everything goes to train",
            file=sys.stderr,
        )

    if out.exists():
        for name in ("frames", *(f"{s}.jsonl" for s in SPLITS)):
            target = out / name
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    rows: dict[str, list[dict]] = {s: [] for s in SPLITS}
    stats = Counter()
    skipped: list[str] = []
    for clip in sorted(clips, key=lambda c: c.clip_id):
        split = assignment[clip.source_video]
        for view in clip.views:
            seed_for_sample = int(_h(f"{seed}|{clip.clip_id}|{view.camera}")[:16], 16)
            rng = random.Random(seed_for_sample)  # noqa: S311 - sampling, not security
            n = rng.randint(frames_min, frames_max)
            times = frame_times(clip_duration(clip), n)
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

    files = {}
    for split, items in rows.items():
        path = out / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in items))
        files[path.name] = sha256_file(path)
    frame_hashes = sorted(
        (p.relative_to(out).as_posix(), sha256_file(p)) for p in (out / "frames").rglob("*.jpg")
    )
    label_counts = Counter(label for items in rows.values() for r in items for label in r["labels"])

    splits_path.write_text(
        json.dumps(
            {"seed": seed, "fractions": list(fractions), "assignments": assignment},
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
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
        "splits": {s: sorted(v for v, a in assignment.items() if a == s) for s in SPLITS},
        "files": files,
        "frames_sha256": _h(json.dumps(frame_hashes)),
        "skipped": skipped,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (out / "dataset-metadata.json").write_text(
        json.dumps(
            {
                "title": "GenAI-VMS TG phase grounding",
                "id": "YOUR_KAGGLE_USERNAME/genai-vms-tg-phase",
                "licenses": [{"name": "other"}],
            },
            indent=1,
        )
        + "\n"
    )
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
