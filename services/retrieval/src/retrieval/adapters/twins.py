"""Reads twin documents (`twin.v1` JSON in `vms-twins`) to build the excerpt the reasoning
rerank shows the model: who was in the window, what they looked like and where they were."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from vms_common.contracts.twin import TwinV1
from vms_common.logging import get_logger
from vms_common.storage.s3 import S3Client

log = get_logger(__name__)


class TwinReader:
    def __init__(self, s3: S3Client) -> None:
        self._s3 = s3

    async def load(self, uri: str) -> TwinV1 | None:
        try:
            return TwinV1.model_validate(json.loads(await self._s3.get_bytes(uri)))
        except Exception as exc:  # a missing/old twin must not fail a search
            log.warning("twin_unreadable", uri=uri, error=str(exc))
            return None

    async def exists(self, uri: str) -> bool:
        try:
            return await self._s3.exists(uri)
        except Exception as exc:  # unreachable storage must not empty every search
            log.warning("media_check_failed", uri=uri, error=str(exc))
            return True

    async def load_many(self, uris: list[str]) -> dict[str, TwinV1]:
        twins = await asyncio.gather(*(self.load(u) for u in uris))
        return {u: t for u, t in zip(uris, twins, strict=True) if t is not None}


def excerpt_lines(
    twins: list[TwinV1], *, start_ms: int, end_ms: int, track_ids: set[str], max_tracks: int = 6
) -> list[str]:
    """Short factual lines about the window, matched tracks first. Capped hard: this is prompt
    text for a 3B model with an 8k window shared by five candidates."""
    persons = 0
    per_track: dict[str, dict] = {}
    seen_frames = 0
    for twin in twins:
        for fr in twin.frames:
            t = int(fr.ts.timestamp() * 1000)
            if t < start_ms - 3000 or t > end_ms + 3000:
                continue
            seen_frames += 1
            persons = max(persons, sum(1 for o in fr.objects if o.category == "person"))
            for o in fr.objects:
                d = per_track.setdefault(
                    o.track_id,
                    {"cat": o.category, "colors": set(), "zones": set(), "n": 0, "speed": []},
                )
                d["n"] += 1
                a = o.attributes
                for c in (a.upper_color, a.lower_color, a.color):
                    if c:
                        d["colors"].add(c)
                d["zones"].update(o.zones)
                if o.motion:
                    d["speed"].append(o.motion.speed)

    if not seen_frames:
        return []
    lines = [f"up to {persons} person(s) visible in the window"]
    ranked = sorted(per_track.items(), key=lambda kv: (kv[0] not in track_ids, -kv[1]["n"]))
    by_cat: dict[str, int] = defaultdict(int)
    for _tid, d in per_track.items():
        by_cat[d["cat"]] += 1
    others = ", ".join(f"{n} {c}" for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1])[:4])
    lines.append(f"objects tracked: {others}")
    for tid, d in ranked[:max_tracks]:
        mark = "MATCH " if tid in track_ids else ""
        speed = f", avg speed {sum(d['speed']) / len(d['speed']):.2f}" if d["speed"] else ""
        colors = "/".join(sorted(d["colors"])) or "unknown colour"
        zones = ",".join(sorted(d["zones"])) or "no zone"
        lines.append(f"{mark}{d['cat']} ({colors}) in {zones}, seen {d['n']}x{speed}")
    return lines
