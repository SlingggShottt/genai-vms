"""Builds the study guide PDF:  .venv/bin/python docs/study_guide/build.py

The text is in part1..part5.html, the diagrams are drawn by figures_a.py / figures_b.py (plain SVG,
no images), the look is style.css; WeasyPrint turns it into one PDF."""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import figures_a  # noqa: E402
import figures_b  # noqa: E402
import weasyprint  # noqa: E402

FIGURES = {
    name: fn
    for module in (figures_a, figures_b)
    for name, fn in vars(module).items()
    if callable(fn) and not name.startswith("_") and name not in {"Canvas", "chain", "bars"}
}


def main() -> None:
    body = "".join((HERE / f"part{i}.html").read_text() for i in range(1, 6))
    used: list[str] = []

    def draw(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in FIGURES:
            raise SystemExit(f"no figure called {name!r}")
        used.append(name)
        return FIGURES[name]()

    body = re.sub(r"<!--FIG:([a-z_]+)-->", draw, body)
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>GenAI-VMS study guide</title>"
        f"<style>{(HERE / 'style.css').read_text()}</style></head><body>{body}</body></html>"
    )
    (HERE / "guide.html").write_text(html)
    out = HERE / "GenAI-VMS-Study-Guide.pdf"
    weasyprint.HTML(string=html, base_url=str(HERE)).write_pdf(str(out))
    print(f"{len(used)} figures, wrote {out}")


if __name__ == "__main__":
    main()
