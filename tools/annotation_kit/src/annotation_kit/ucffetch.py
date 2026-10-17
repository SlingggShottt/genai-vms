"""Fetch only the UCF-Crime videos that have a labelled crime window, from a Hugging Face mirror.

The full UCF-Crime release is over a hundred gigabytes, and the official host (www.crcv.ucf.edu)
failed its certificate check when this was written. A mirror (`AllenXeon/ucf_crime`, the same
`Anomaly-Videos-Part-N/<Class>/` layout and the same 950 anomaly videos as the release) stores the
videos one by one, so the labelled ones can be taken without the rest. Those are the *test* videos
listed in `Temporal_Anomaly_Annotation_for_Testing_Videos.txt`, the only ones with start and end
times for the crime; about 140 videos, 3 GB for all thirteen classes.

Licence: the mirror's card says CC0, the original release says research use only. Treat it as
research use only and do not redistribute the files.

Everything goes through two small functions so that it can be tested without the network:
`get_json(url)` and `open_url(url)`.
"""

from __future__ import annotations

import json
import re
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from annotation_kit.ucf import read_temporal_annotations

REPO = "AllenXeon/ucf_crime"
PARTS = 4
ANNOTATION_PATH = "UCF_Crimes-Train-Test-Split/Temporal_Anomaly_Annotation_for_Testing_Videos.txt"
ANNOTATION_FILE = "Temporal_Anomaly_Annotation_for_Testing_Videos.txt"
_TREE = "https://huggingface.co/api/datasets/{repo}/tree/main/{path}?recursive=false&expand=false"
_RESOLVE = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"
_SAFE_NAME = re.compile(r"^[A-Za-z]+\d+(?:_x264)?\.(?:mp4|avi)$")
_SAFE_CLASS = re.compile(r"^[A-Za-z]+$")

JsonGetter = Callable[[str], Any]
UrlOpener = Callable[[str], IO[bytes]]


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Item:
    name: str  # "Abuse028_x264.mp4"
    cls: str  # "Abuse"
    path: str  # where the mirror keeps it
    size: int


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    not_on_mirror: list[str] = field(default_factory=list)  # labelled, but the mirror lacks them

    @property
    def bytes(self) -> int:
        return sum(i.size for i in self.items)

    def by_class(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for item in self.items:
            n, b = out.get(item.cls, (0, 0))
            out[item.cls] = (n + 1, b + item.size)
        return dict(sorted(out.items()))


def http_json(url: str, *, timeout: float = 60.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed https host
        return json.load(response)


def http_open(url: str, *, timeout: float = 120.0) -> IO[bytes]:
    return urllib.request.urlopen(url, timeout=timeout)  # type: ignore[no-any-return]  # noqa: S310


def _size(entry: Mapping[str, Any]) -> int:
    return int(entry.get("size") or (entry.get("lfs") or {}).get("size") or 0)


def index_videos(get_json: JsonGetter, repo: str = REPO) -> dict[str, Item]:
    """Every anomaly video the mirror has, by file name, from `Anomaly-Videos-Part-1..4`."""
    found: dict[str, Item] = {}
    for part in range(1, PARTS + 1):
        for folder in get_json(_TREE.format(repo=repo, path=f"Anomaly-Videos-Part-{part}")):
            if folder.get("type") != "directory":
                continue
            cls = folder["path"].rsplit("/", 1)[-1]
            if not _SAFE_CLASS.match(cls):
                continue
            for entry in get_json(_TREE.format(repo=repo, path=folder["path"])):
                name = entry["path"].rsplit("/", 1)[-1]
                if entry.get("type") == "file" and _SAFE_NAME.match(name):
                    found[name] = Item(name, cls, entry["path"], _size(entry))
    return found


def plan_downloads(
    annotations: Mapping[str, tuple[str, Sequence[Any]]],
    index: Mapping[str, Item],
    classes: Collection[str],
) -> Plan:
    """The labelled videos of the wanted classes (case-insensitive), in name order."""
    wanted = {c.casefold() for c in classes}
    plan = Plan()
    for name in sorted(annotations):
        cls, _spans = annotations[name]
        if cls.casefold() not in wanted:
            continue
        item = index.get(name)
        if item is None:
            plan.not_on_mirror.append(name)
        else:
            plan.items.append(item)
    return plan


def fetch_annotations(out_dir: Path, open_url: UrlOpener, repo: str = REPO) -> Path:
    target = out_dir / ANNOTATION_FILE
    out_dir.mkdir(parents=True, exist_ok=True)
    with open_url(_RESOLVE.format(repo=repo, path=ANNOTATION_PATH)) as src:
        data = src.read()
    if not data.strip():
        raise FetchError("the annotation file came back empty")
    target.write_bytes(data)
    if not read_temporal_annotations(target):
        raise FetchError("the annotation file has no lines this reader understands")
    return target


@dataclass
class FetchReport:
    downloaded: int = 0
    kept: int = 0
    failed: list[str] = field(default_factory=list)


def fetch_videos(
    plan: Plan,
    out_dir: Path,
    open_url: UrlOpener,
    *,
    repo: str = REPO,
    retries: int = 3,
    on_progress: Callable[[int, int, Item], None] | None = None,
) -> FetchReport:
    """Download each video to `out_dir/Videos/<Class>/<name>` through a `.part` file. A file that is
    already there with the size the mirror lists is kept; one that arrives with another size is
    retried and, if it stays wrong, reported and removed."""
    report = FetchReport()
    for number, item in enumerate(plan.items, start=1):
        target = out_dir / "Videos" / item.cls / item.name
        if target.is_file() and (not item.size or target.stat().st_size == item.size):
            report.kept += 1
            if on_progress:
                on_progress(number, len(plan.items), item)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        for attempt in range(1, retries + 1):
            try:
                with (
                    open_url(_RESOLVE.format(repo=repo, path=item.path)) as src,
                    part.open("wb") as dst,
                ):
                    shutil.copyfileobj(src, dst, length=1 << 20)
                if item.size and part.stat().st_size != item.size:
                    raise FetchError(
                        f"{item.name}: got {part.stat().st_size} bytes, wanted {item.size}"
                    )
                part.replace(target)
                report.downloaded += 1
                break
            except (OSError, urllib.error.URLError, FetchError):
                part.unlink(missing_ok=True)
                if attempt == retries:
                    report.failed.append(item.name)
        if on_progress:
            on_progress(number, len(plan.items), item)
    return report


def format_plan(plan: Plan) -> str:
    lines = ["| class | videos | size |", "|---|---:|---:|"]
    for cls, (n, b) in plan.by_class().items():
        lines.append(f"| {cls} | {n} | {b / 1e6:.0f} MB |")
    lines.append(f"| **all** | {len(plan.items)} | {plan.bytes / 1e6:.0f} MB |")
    if plan.not_on_mirror:
        lines.append(f"\nlabelled but not on the mirror: {', '.join(plan.not_on_mirror)}")
    return "\n".join(lines)
