"""PhaVR dataset builder (P5-J1): verified phase captions + VQA answers -> instruction data.

    uv run python ml/training/phavr/build_dataset.py \
        --labels phavr_labels.jsonl --phase-labels phase_labels.jsonl \
        --videos-root /path/to/evidence --out datasets/phavr-v1

Reads `phavr_labels.jsonl` (`phavr_label.v1`: the caption and VQA answers a person verified for one
phase of one clip in one camera's view) and `phase_labels.jsonl` (only for where each view's video
is). For every label it samples 2-4 frames from inside the phase, renders the prompt EXACTLY as
`services/reasoning/steps/readings.py` does at inference (the `phase_vr` prompt, the stage meaning,
the event type's questions from `config/vqa_bank.yaml`, times on the clip's clock) and writes the
answer the service parses (`ViewDraft`): a caption and one canonical answer per question.

Layout, hashing, the split rules and the frame code are the TG builder's (`dataset_common.py`), and
the splits come from the SAME `splits.json`: pass the TG builder's file with `--splits` so a source
video is in the same split for both adapters and neither can leak the other's test set.

A question is asked only if the label has an answer to it, so a verified label never teaches the
model to answer something nobody checked; labels whose answer is not in the bank's vocabulary, or
whose caption is empty, are skipped and listed in the manifest.
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

from annotation_kit.schema import PhaseLabelClip, PhavrLabel  # noqa: E402
from dataset_common import (  # noqa: E402
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
    write_kaggle_metadata,
    write_split_files,
    write_splits,
)
from pydantic import ValidationError  # noqa: E402
from reasoning.domain.sampling import pick_evenly  # noqa: E402
from reasoning.domain.timeline import PHASE_MEANING  # noqa: E402
from vms_common.llm import render_prompt  # noqa: E402
from vms_common.llm.prompts import PROMPTS_DIR  # noqa: E402
from vms_common.vqa_bank import VQABank, VQAQuestion, load_vqa_bank  # noqa: E402

PROMPT_NAME = "phase_vr"
PROMPT_VERSION = "1.0"
FRAME_FPS = 2.0  # perception's normal rate (1 when it falls behind), as in the TG builder
REPO = Path(__file__).resolve().parents[3]


def load_labels(path: Path) -> list[PhavrLabel]:
    labels, problems = [], []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            labels.append(PhavrLabel.model_validate_json(line))
        except ValidationError as exc:
            problems.append(f"line {n}: {exc.errors()[0]['msg']}")
        except ValueError as exc:
            problems.append(f"line {n}: {exc}")
    keys = Counter((x.clip_id, x.view, x.phase) for x in labels)
    problems += [f"{'|'.join(k)} appears {n} times" for k, n in keys.items() if n > 1]
    if problems:
        raise LabelError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    if not labels:
        raise LabelError(f"{path}: no labels")
    return labels


def load_views(path: Path) -> dict[tuple[str, str], str]:
    """(clip_id, camera) -> video uri, from the phase labels."""
    out: dict[tuple[str, str], str] = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            clip = PhaseLabelClip.model_validate_json(line)
        except ValueError as exc:
            raise LabelError(f"{path}: line {n}: {exc}") from exc
        for view in clip.views:
            out[(clip.clip_id, view.camera)] = view.video_uri
    return out


def span_frame_times(start_s: float, end_s: float, n: int, fps: float = FRAME_FPS) -> list[float]:
    """The frames inside the stage, spread evenly; a stage too short to hold one gets the frame
    nearest its middle (what the service does, because it would otherwise have no evidence)."""
    first = math.ceil(start_s * fps - 1e-9)
    inside = [k / fps for k in range(first, math.floor(end_s * fps + 1e-9) + 1)]
    if inside:
        return pick_evenly(inside, n)
    return [round(((start_s + end_s) / 2) * fps) / fps]


def answers_for(
    label: PhavrLabel, questions: tuple[VQAQuestion, ...]
) -> tuple[list[tuple[VQAQuestion, str]], list[str]]:
    """The questions to ask (those the label answers, in bank order) with their canonical answers,
    and the problems found: an answer outside the question's vocabulary."""
    given = {item.id: item.a for item in label.vqa}
    asked, problems = [], []
    for q in questions:
        if q.id not in given:
            continue
        canon = {a.casefold(): a for a in q.answers}
        value = canon.get(given[q.id].strip().casefold().rstrip("."))
        if value is None:
            problems.append(f"{q.id}: {given[q.id]!r} is not one of {list(q.answers)}")
            continue
        asked.append((q, value))
    return asked, problems


def render_user_prompt(label: PhavrLabel, times: list[float], questions: list[VQAQuestion]) -> str:
    return render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        event_type=label.event_type.replace("_", " "),
        phase=label.phase,
        phase_meaning=PHASE_MEANING[label.phase],
        camera=label.view,
        n_frames=len(times),
        times=[round(t, 1) for t in times],
        questions=[{"id": q.id, "text": q.text, "answers": list(q.answers)} for q in questions],
    )


def sample_record(
    label: PhavrLabel,
    split: str,
    times: list[float],
    asked: list[tuple[VQAQuestion, str]],
    images: list[str],
) -> dict:
    questions = [q for q, _ in asked]
    answer = {
        "caption": label.caption.strip(),
        "answers": [{"id": q.id, "answer": value} for q, value in asked],
    }
    return {
        "id": f"{label.clip_id}|{label.view}|{label.phase}",
        "clip_id": label.clip_id,
        "source_video": label.source_video,
        "split": split,
        "camera": label.view,
        "event_type": label.event_type,
        "phase": label.phase,
        "start_s": label.start_s,
        "end_s": label.end_s,
        "images": images,
        "frame_times": [round(t, 1) for t in times],
        "caption": answer["caption"],
        "answers": answer["answers"],
        "had_draft": label.pseudo is not None,
        "edits": label.edits.model_dump() if label.edits else None,  # how far a person moved it
        "messages": [
            {
                "role": "user",
                "content": [
                    *({"type": "image", "image": path} for path in images),
                    {"type": "text", "text": render_user_prompt(label, times, questions)},
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": json.dumps(answer)}]},
        ],
    }


def build(
    labels_path: Path,
    phase_labels_path: Path,
    videos_root: Path,
    out: Path,
    *,
    bank: VQABank | None = None,
    splits_path: Path | None = None,
    fractions: tuple[float, float, float] = (0.7, 0.15, 0.15),
    frames_min: int = 2,
    frames_max: int = 4,
    frame_fps: float = FRAME_FPS,
    seed: int = 7,
) -> dict:
    if not 1 <= frames_min <= frames_max <= 4:
        raise ValueError(
            "frames must satisfy 1 <= frames_min <= frames_max <= 4 (the service's cap)"
        )
    bank = bank or load_vqa_bank(REPO / "config" / "vqa_bank.yaml")
    labels = load_labels(labels_path)
    views = load_views(phase_labels_path)
    splits_path = splits_path or out / "splits.json"
    videos = sorted({x.source_video for x in labels})
    assignment = assign_splits(videos, read_splits(splits_path), fractions, seed)
    if len(videos) < 3:
        print(f"WARNING: only {len(videos)} source video(s)", file=sys.stderr)

    clear_outputs(out)
    rows: dict[str, list[dict]] = {s: [] for s in SPLITS}
    skipped: list[str] = []
    stats = Counter()
    for label in sorted(labels, key=lambda x: (x.clip_id, x.view, x.phase)):
        key = f"{label.clip_id}|{label.view}|{label.phase}"
        if not label.caption.strip():
            skipped.append(f"{key}: empty caption")
            continue
        uri = views.get((label.clip_id, label.view))
        if uri is None:
            skipped.append(f"{key}: no such view in the phase labels")
            continue
        video = resolve_video(uri, videos_root)
        if not video.is_file():
            skipped.append(f"{key}: video not found at {video}")
            continue
        asked, problems = answers_for(label, bank.questions_for(label.event_type))
        if problems:
            skipped.append(f"{key}: " + "; ".join(problems))
            continue
        rng = random.Random(int(sha256_text(f"{seed}|{key}")[:16], 16))  # noqa: S311
        times = span_frame_times(
            label.start_s, label.end_s, rng.randint(frames_min, frames_max), frame_fps
        )
        frame_dir = out / "frames" / label.clip_id / label.view / label.phase
        paths = extract_frames(video, times, frame_dir)
        images = [str(p.relative_to(out)) for p in paths]
        split = assignment[label.source_video]
        rows[split].append(sample_record(label, split, times, asked, images))
        stats["samples"] += 1
        stats["frames"] += len(times)
        stats["questions"] += len(asked)
        stats["unasked_bank_questions"] += len(bank.questions_for(label.event_type)) - len(asked)
    if not stats["samples"]:
        raise LabelError("no sample could be built:\n  " + "\n  ".join(skipped))

    files = write_split_files(out, rows)
    write_splits(splits_path, assignment, fractions, seed)
    prompt_file = PROMPTS_DIR / PROMPT_NAME / f"{PROMPT_VERSION}.md"
    manifest = {
        "schema": "phavr_dataset.v1",
        "builder": "ml/training/phavr/build_dataset.py",
        "prompt": {
            "name": PROMPT_NAME,
            "version": PROMPT_VERSION,
            "sha256": sha256_file(prompt_file),
        },
        "vqa_bank_sha256": sha256_file(REPO / "config" / "vqa_bank.yaml"),
        "config": {
            "frames_min": frames_min,
            "frames_max": frames_max,
            "frame_fps": frame_fps,
            "max_height": 360,
            "seed": seed,
            "fractions": list(fractions),
        },
        "source_labels_sha256": sha256_file(labels_path),
        "counts": {
            "labels": len(labels),
            "source_videos": len(videos),
            "samples": {s: len(rows[s]) for s in SPLITS},
            "frames": stats["frames"],
            "questions_asked": stats["questions"],
            "bank_questions_without_an_answer": stats["unasked_bank_questions"],
            "phases": dict(sorted(Counter(r["phase"] for v in rows.values() for r in v).items())),
        },
        "splits": {s: sorted(v for v in videos if assignment[v] == s) for s in SPLITS},
        "files": files,
        "frames_sha256": frames_digest(out),
        "skipped": skipped,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    write_kaggle_metadata(out, "GenAI-VMS PhaVR phase captions and VQA", "genai-vms-phavr")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", type=Path, required=True, help="phavr_labels.jsonl")
    ap.add_argument(
        "--phase-labels", type=Path, required=True, help="phase_labels.jsonl (video uris)"
    )
    ap.add_argument("--videos-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--splits", type=Path, default=None, help="the TG builder's splits.json")
    ap.add_argument("--frames-min", type=int, default=2)
    ap.add_argument("--frames-max", type=int, default=4)
    ap.add_argument("--frame-fps", type=float, default=FRAME_FPS)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    try:
        manifest = build(
            args.labels,
            args.phase_labels,
            args.videos_root,
            args.out,
            splits_path=args.splits,
            frames_min=args.frames_min,
            frames_max=args.frames_max,
            frame_fps=args.frame_fps,
            seed=args.seed,
        )
    except LabelError as exc:
        sys.exit(str(exc))
    c = manifest["counts"]
    print(f"{c['samples']} samples from {c['labels']} labels / {c['source_videos']} source videos")
    print(f"{c['frames']} frames, {c['questions_asked']} questions")
    for line in manifest["skipped"]:
        print(f"skipped {line}")


if __name__ == "__main__":
    main()
