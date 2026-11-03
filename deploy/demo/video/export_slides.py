"""Writes the study guide's SVG figures to slides/ for the intro and outro of the demo video.

    .venv/bin/python deploy/demo/video/export_slides.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "docs" / "study_guide"))

import figures_a  # noqa: E402
import figures_b  # noqa: E402

WANTED = ["problem", "big_picture", "clip_journey", "twin", "events", "correlation", "search", "phases", "gateway",
          "retrieval_chart", "adapter_chart", "latency_chart"]  # fmt: skip

(HERE / "slides").mkdir(exist_ok=True)
for name in WANTED:
    fn = getattr(figures_a, name, None) or getattr(figures_b, name)
    (HERE / "slides" / f"{name}.svg").write_text(fn())
print(f"wrote {len(WANTED)} slides to {HERE / 'slides'}")
