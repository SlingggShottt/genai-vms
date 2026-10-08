"""What the training-data builders share: splits by source video, hashing, frames from video.

Not a package: the builders (`ml/training/<adapter>/build_dataset.py`) put this folder on
`sys.path` and `import dataset_common`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

SPLITS = ("train", "val", "test")
MAX_HEIGHT = 360


class LabelError(Exception):
    """The labels file is unusable; the message lists every problem found."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    """Every assignment in `existing` is kept, including videos missing from `videos` (another
    builder, or an earlier labels file, may still use them); new videos fill what each split still
    lacks. Deterministic: new videos are taken in the order of a seeded hash, not the order they
    appear in the file. Returns the whole mapping."""
    assignment = dict(existing)
    new = sorted(
        (v for v in videos if v not in assignment), key=lambda v: sha256_text(f"{seed}|{v}")
    )
    want = target_counts(len(assignment) + len(new), fractions)
    have = Counter(assignment.values())
    for v in new:
        # the split furthest below its target; ties go train, val, test
        split = max(SPLITS, key=lambda s: (want[s] - have[s], -SPLITS.index(s)))
        assignment[v] = split
        have[split] += 1
    return assignment


def read_splits(path: Path) -> dict[str, str]:
    return json.loads(path.read_text())["assignments"] if path.exists() else {}


def write_splits(path: Path, assignment: dict[str, str], fractions, seed: int) -> None:
    path.write_text(
        json.dumps(
            {"seed": seed, "fractions": list(fractions), "assignments": assignment},
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )


def write_split_files(out: Path, rows: dict[str, list[dict]]) -> dict[str, str]:
    """`<split>.jsonl` for each split; returns {file name: sha256}."""
    files = {}
    for split, items in rows.items():
        path = out / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in items))
        files[path.name] = sha256_file(path)
    return files


def frames_digest(out: Path) -> str:
    """One hash for every frame under `out/frames` (path and content)."""
    hashes = sorted(
        (p.relative_to(out).as_posix(), sha256_file(p)) for p in (out / "frames").rglob("*.jpg")
    )
    return sha256_text(json.dumps(hashes))


def clear_outputs(out: Path) -> None:
    """Remove what a build writes (not `splits.json`, which must survive a rebuild)."""
    if out.exists():
        for name in ("frames", *(f"{s}.jsonl" for s in SPLITS)):
            target = out / name
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
    out.mkdir(parents=True, exist_ok=True)


def write_kaggle_metadata(out: Path, title: str, slug: str) -> None:
    (out / "dataset-metadata.json").write_text(
        json.dumps(
            {
                "title": title,
                "id": f"YOUR_KAGGLE_USERNAME/{slug}",
                "licenses": [{"name": "other"}],
            },
            indent=1,
        )
        + "\n"
    )


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
