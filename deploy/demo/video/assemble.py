"""Joins the recorded scenes into one MP4 + SRT + narration script.

    .venv/bin/python deploy/demo/video/assemble.py [scene-id ...]      # default: every scene in out/ (name order)

Scenes are encoded first when their demo.mp4 is missing or older than the recording. Output:
out/final/GenAI-VMS-demo.mp4, .srt (captions, soft subtitles) and narration.md (the same captions
with timestamps, to read aloud if you want to add your own voice-over).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PY = sys.executable


def stamp(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def short(sec: float) -> str:
    return f"{int(sec) // 60}:{int(sec) % 60:02}"


def main() -> None:
    wanted = sys.argv[1:]
    scenes = sorted(d for d in OUT.iterdir() if d.is_dir() and (d / "timeline.json").exists() and d.name[:2].isdigit())
    if wanted:
        scenes = [d for d in scenes if any(d.name.startswith(w) for w in wanted)]
    names = []
    for d in scenes:
        if (d / "error.txt").exists():
            sys.exit(f"{d.name} failed when it was recorded (see {d / 'error.txt'}): re-record it first")
        mp4 = d / "demo.mp4"
        if not mp4.exists() or mp4.stat().st_mtime < (d / "timeline.json").stat().st_mtime:
            subprocess.run([PY, str(HERE / "encode.py"), str(d)], check=True, env={**os.environ, "PRESET": os.environ.get("PRESET", "slow")})
        names.append(d)

    final = OUT / "final"
    final.mkdir(exist_ok=True)
    (final / "list.txt").write_text("".join(f"file '{d.name}/demo.mp4'\n" for d in names).replace("file '", "file '../"))
    subprocess.run(
        ["sg", "docker", "-c",
         f"docker run --rm -v '{OUT}':/work -w /work/final --entrypoint ffmpeg genai-vms-camera-sim "
         f"-hide_banner -loglevel error -y -f concat -safe 0 -i list.txt -c copy -movflags +faststart GenAI-VMS-demo.mp4"],
        check=True,
    )

    # captions of every scene, shifted by the scenes before it
    offset = 0.0
    srt, script = [], ["# Demo video: what is on screen, with timestamps\n", "Read these aloud (or paraphrase) for a voice-over.\n"]
    n = 0
    for d in names:
        dur = json.loads((d / "meta.json").read_text())["seconds"]
        script.append(f"\n## {d.name}  ({short(offset)})\n")
        for block in (d / "demo.srt").read_text().strip().split("\n\n") if (d / "demo.srt").read_text().strip() else []:
            lines = block.split("\n")
            a, b = lines[1].split(" --> ")

            def secs(t: str) -> float:
                h, m, rest = t.split(":")
                sec, ms = rest.split(",")
                return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000

            n += 1
            text = "\n".join(lines[2:])
            srt.append(f"{n}\n{stamp(offset + secs(a))} --> {stamp(offset + secs(b))}\n{text}\n")
            script.append(f"- **{short(offset + secs(a))}** {text.replace(chr(10), ' - ')}\n")
        offset += dur
    (final / "GenAI-VMS-demo.srt").write_text("\n".join(srt))
    (final / "narration.md").write_text("".join(script))
    size = (final / "GenAI-VMS-demo.mp4").stat().st_size / 1e6
    print(f"wrote {final / 'GenAI-VMS-demo.mp4'}  {short(offset)} min, {size:.0f} MB")


if __name__ == "__main__":
    main()
