"""A tiny SVG drawing toolkit for the study guide's diagrams: boxes, cylinders, arrows, labels.

Everything is plain SVG text, so WeasyPrint draws it into the PDF as vectors. Colours come from
one palette so that the same kind of thing is always the same colour across the whole guide."""

from __future__ import annotations

from html import escape

PALETTE = {
    "media": ("#dbeafe", "#2563eb"),  # cameras, streams, video plumbing
    "ai": ("#dcfce7", "#16a34a"),  # models, GenAI
    "event": ("#ffedd5", "#ea580c"),  # rules, alerts, events
    "store": ("#f3e8ff", "#7c3aed"),  # databases, storage
    "ui": ("#fce7f3", "#db2777"),  # what the person sees
    "plain": ("#f1f5f9", "#64748b"),  # neutral
    "warn": ("#fef9c3", "#ca8a04"),  # caveats, honesty boxes
    "bad": ("#fee2e2", "#dc2626"),
}
FONT = "DejaVu Sans, Arial, sans-serif"


class Canvas:
    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.parts: list[str] = []

    # ---- primitives ----------------------------------------------------------------------
    def text(
        self, x: float, y: float, s: str, *, size: int = 12, anchor: str = "middle",
        bold: bool = False, color: str = "#111827", italic: bool = False,
    ) -> None:  # fmt: skip
        """`s` may hold \\n for several lines (centred on y)."""
        lines = s.split("\n")
        line_h = size * 1.25
        top = y - (len(lines) - 1) * line_h / 2
        for i, line in enumerate(lines):
            weight = ' font-weight="bold"' if bold else ""
            slant = ' font-style="italic"' if italic else ""
            self.parts.append(
                f'<text x="{x:.1f}" y="{top + i * line_h + size * 0.35:.1f}" text-anchor="{anchor}" '
                f'font-family="{FONT}" font-size="{size}" fill="{color}"{weight}{slant}>'
                f"{escape(line)}</text>"
            )

    def box(
        self, x: float, y: float, w: float, h: float, label: str = "", kind: str = "plain",
        *, size: int = 12, bold: bool = False, rx: int = 9, dashed: bool = False, sub: str = "",
    ) -> tuple[float, float, float, float]:  # fmt: skip
        fill, stroke = PALETTE[kind]
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.6"{dash}/>'
        )
        if sub:
            self.text(x + w / 2, y + h / 2 - size * 0.55, label, size=size, bold=bold)
            self.text(x + w / 2, y + h / 2 + size * 0.95, sub, size=max(size - 3, 8), color="#475569")
        elif label:
            self.text(x + w / 2, y + h / 2, label, size=size, bold=bold)
        return (x, y, w, h)

    def cylinder(
        self, x: float, y: float, w: float, h: float, label: str = "", kind: str = "store", *, size: int = 12
    ) -> tuple[float, float, float, float]:  # fmt: skip
        fill, stroke = PALETTE[kind]
        ry = min(10, h * 0.16)
        self.parts.append(
            f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0 1 {w},0 v{h - 2 * ry} a{w / 2},{ry} 0 0 1 {-w},0 z" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
            f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
        )
        self.text(x + w / 2, y + h / 2 + ry * 0.6, label, size=size, bold=True)
        return (x, y, w, h)

    def group(
        self, x: float, y: float, w: float, h: float, title: str, kind: str = "plain", *, right: bool = False
    ) -> None:  # fmt: skip
        _, stroke = PALETTE[kind]
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" fill="none" '
            f'stroke="{stroke}" stroke-width="1.4" stroke-dasharray="3 4"/>'
        )
        if right:
            self.text(x + w - 12, y + 14, title, size=11, anchor="end", bold=True, color=stroke)
        else:
            self.text(x + 12, y + 14, title, size=11, anchor="start", bold=True, color=stroke)

    def arrow(
        self, x1: float, y1: float, x2: float, y2: float, label: str = "", *, color: str = "#334155",
        dashed: bool = False, size: int = 10, label_at: float = 0.5, dy: float = -9,
    ) -> None:  # fmt: skip
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
            f'stroke-width="1.7"{dash} marker-end="url(#arr)"/>'
        )
        if label:
            mx, my = x1 + (x2 - x1) * label_at, y1 + (y2 - y1) * label_at + dy
            self.text(mx, my, label, size=size, color="#334155", italic=True)

    def poly_arrow(self, pts: list[tuple[float, float]], label: str = "", *, color: str = "#334155", dashed: bool = False) -> None:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.parts.append(
            f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.7"{dash} marker-end="url(#arr)"/>'
        )
        if label:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            self.text((x1 + x2) / 2, (y1 + y2) / 2 - 8, label, size=10, italic=True, color="#334155")

    def pill(self, x: float, y: float, w: float, label: str, kind: str = "plain", *, size: int = 10) -> None:
        fill, stroke = PALETTE[kind]
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="18" rx="9" fill="{fill}" stroke="{stroke}"/>'
        )
        self.text(x + w / 2, y + 9, label, size=size)

    def circle(self, cx: float, cy: float, r: float, label: str = "", kind: str = "plain", *, size: int = 11) -> None:
        fill, stroke = PALETTE[kind]
        self.parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        if label:
            self.text(cx, cy, label, size=size, bold=True)

    def raw(self, s: str) -> None:
        self.parts.append(s)

    def render(self) -> str:
        defs = (
            '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#334155"/></marker></defs>'
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="100%" preserveAspectRatio="xMidYMid meet">{defs}{"".join(self.parts)}</svg>'
        )


def chain(c: Canvas, y: float, items: list[tuple[str, str]], x0: float, x1: float, h: float = 54, *, gap: float = 26, size: int = 12):
    """Boxes left to right with arrows between them; returns each box's (x, y, w, h)."""
    n = len(items)
    w = (x1 - x0 - gap * (n - 1)) / n
    boxes = []
    for i, (label, kind) in enumerate(items):
        bx = x0 + i * (w + gap)
        boxes.append(c.box(bx, y, w, h, label, kind, size=size))
        if i:
            c.arrow(bx - gap + 2, y + h / 2, bx - 2, y + h / 2)
    return boxes
