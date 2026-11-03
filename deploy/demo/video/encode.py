"""Turns a recording (frames + timeline.json from record.mjs) into an MP4 and an SRT.

    .venv/bin/python deploy/demo/video/encode.py [out/<run>]    # default: deploy/demo/video/out/latest

The screencast only delivers a frame when the picture changes, so every frame is shown until the
next one arrives (ffmpeg concat with durations). Stretches marked "sped up" are shown `factor` times
faster. The captions become an SRT (also burned in already: they are drawn in the page).
ffmpeg runs in the camera-sim image (no ffmpeg on the host).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FPS = 30


def out_time(t: float, speed: list[dict], t_first: float) -> float:
    """Source time -> time in the final video, with every sped-up stretch shortened."""
    out = t - t_first
    for s in speed:
        if s["t1"] is None:
            continue
        a, b = s["t0"], s["t1"]
        if t <= a:
            continue
        inside = min(t, b) - a
        out -= inside * (1 - 1 / s["factor"])
    return out


def srt_stamp(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def main() -> None:
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "out" / "latest"
    run = run.resolve()
    tl = json.loads((run / "timeline.json").read_text())
    frames = tl["frames"]
    speed = tl["speed"]
    if not frames:
        sys.exit("no frames recorded")
    # a scene starts on a blank page and the app paints in steps: skip the leading frames that are
    # near-empty (black, or a half-drawn shell) - the first frame at least half as big as the typical early frame
    sizes = [(run / "frames" / f"{idx:06d}.jpg").stat().st_size for idx, _ in frames]
    ref = sorted(sizes[:60])[len(sizes[:60]) // 2]
    first = next((k for k, size in enumerate(sizes) if size > 15000 and size >= 0.5 * ref), 0)
    frames = frames[first:]
    # closing the browser paints one last blank frame: drop trailing near-empty frames too
    while len(frames) > 1 and (run / "frames" / f"{frames[-1][0]:06d}.jpg").stat().st_size < 15000:
        frames.pop()
    t_first = frames[0][1]
    t_end = frames[-1][1] + 1.0

    # concat list: each frame lasts until the next one (shortened inside a sped-up stretch)
    lines: list[str] = []
    for k, (idx, ts) in enumerate(frames):
        nxt = frames[k + 1][1] if k + 1 < len(frames) else t_end
        dur = out_time(nxt, speed, t_first) - out_time(ts, speed, t_first)
        if dur <= 0:
            continue
        lines.append(f"file 'frames/{idx:06d}.jpg'\nduration {dur:.5f}")
    lines.append(f"file 'frames/{frames[-1][0]:06d}.jpg'")  # concat quirk: last file listed again
    (run / "frames.txt").write_text("\n".join(lines) + "\n")

    # captions -> SRT (the caption stays until the next one; empty text clears it)
    caps = tl["captions"]
    srt: list[str] = []
    n = 0
    for k, c in enumerate(caps):
        if not c["title"]:
            continue
        start = max(out_time(c["t"], speed, t_first), 0.0)
        end = max(out_time(caps[k + 1]["t"] if k + 1 < len(caps) else t_end, speed, t_first), 0.0)
        if end - start < 0.4:
            continue
        n += 1
        text = c["title"] + (f"\n{c['sub']}" if c["sub"] else "")
        srt.append(f"{n}\n{srt_stamp(start)} --> {srt_stamp(end)}\n{text}\n")
    (run / "demo.srt").write_text("\n".join(srt))

    w, h = tl["width"], tl["height"]
    total = out_time(t_end, speed, t_first)
    fade = f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(total - 0.4, 0):.2f}:d=0.4,"
    cmd = (
        f"docker run --rm -v '{run}':/work -w /work --entrypoint ffmpeg genai-vms-camera-sim "
        f"-hide_banner -loglevel error -y -f concat -safe 0 -i frames.txt "
        f"-vf '{fade}fps={FPS},scale={w}:{h},format=yuv420p' -c:v libx264 -preset {os.environ.get('PRESET', 'slow')} -crf 20 "
        f"-movflags +faststart demo.mp4"
    )
    subprocess.run(["sg", "docker", "-c", cmd], check=True)
    (run / "meta.json").write_text(json.dumps({"seconds": total}))
    print(f"wrote {run / 'demo.mp4'} ({total / 60:.1f} min) and {run / 'demo.srt'}")
    for m in tl.get("marks", []):
        print(f"  {srt_stamp(out_time(m['t'], speed, t_first))[:8]}  {m['name']}")


if __name__ == "__main__":
    main()
