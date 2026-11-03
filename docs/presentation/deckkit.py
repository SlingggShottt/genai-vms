"""Tiny slide toolkit: one description of a slide, two outputs.

A slide is a list of drawing operations in inches (rect, text, pic, arrow, chart). `Deck.save_pptx`
turns them into native, editable PowerPoint shapes and charts; `Deck.preview` draws the same
operations with Pillow (Liberation Sans is metric-compatible with Arial, the deck's font), so the
layout can be checked without PowerPoint, and text that would overflow its box is reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 13.333, 7.5
FONT = "Arial"
PX = 100  # preview pixels per inch

_LIB = "/usr/share/fonts/truetype/liberation/LiberationSans-{}.ttf"


def rgb(hex6: str) -> tuple[int, int, int]:
    return int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)


@dataclass
class Op:
    kind: str
    kw: dict = field(default_factory=dict)


# ---- text markup: **bold** -----------------------------------------------------------------------


def runs_of(text: str) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        if part:
            out.append((part, i % 2 == 1))
    return out


def norm_paras(paras, size, color, bold) -> list[dict]:
    if isinstance(paras, str):
        paras = [paras]
    out = []
    for p in paras:
        d = {"text": p} if isinstance(p, str) else dict(p)
        d.setdefault("size", size)
        d.setdefault("color", color)
        d.setdefault("bold", bold)
        d.setdefault("bullet", False)
        d.setdefault("after", 0)
        out.append(d)
    return out


class Slide:
    def __init__(self, bg: str, notes: str = ""):
        self.ops: list[Op] = []
        self.bg = bg
        self.notes = notes

    def rect(self, x, y, w, h, fill=None, line=None, lw=1.0, r=0.0):
        self.ops.append(Op("rect", dict(x=x, y=y, w=w, h=h, fill=fill, line=line, lw=lw, r=r)))

    def oval(self, x, y, w, h, fill=None, line=None, lw=1.0):
        self.ops.append(Op("oval", dict(x=x, y=y, w=w, h=h, fill=fill, line=line, lw=lw)))

    def text(self, x, y, w, h, paras, size=14, color="F1F5F9", bold=False, align="l", anchor="t", pad=0.06):
        self.ops.append(
            Op("text", dict(x=x, y=y, w=w, h=h, paras=norm_paras(paras, size, color, bold), align=align, anchor=anchor, pad=pad))
        )

    def pic(self, path, x, y, w, h, anchor="c", radius=0.12, border="24324A"):
        self.ops.append(Op("pic", dict(path=str(path), x=x, y=y, w=w, h=h, anchor=anchor, radius=radius, border=border)))

    def arrow(self, x1, y1, x2, y2, color="94A3B8", lw=1.75, head=True):
        self.ops.append(Op("arrow", dict(x1=x1, y1=y1, x2=x2, y2=y2, color=color, lw=lw, head=head)))

    def chart(self, x, y, w, h, cats, series, ymax, fmt="0.00", pct=False):
        self.ops.append(Op("chart", dict(x=x, y=y, w=w, h=h, cats=cats, series=series, ymax=ymax, fmt=fmt, pct=pct)))

    # ---- composite helpers ---------------------------------------------------------------------

    def card(self, x, y, w, h, fill, line=None, r=0.1, lw=1.0):
        self.rect(x, y, w, h, fill=fill, line=line, r=r, lw=lw)

    def node(self, x, y, w, h, title, sub, fill, line, tcolor="F1F5F9", scolor="B6C2D6", tsize=13, ssize=10.5):
        """A labelled box of a flow diagram."""
        self.rect(x, y, w, h, fill=fill, line=line, lw=1.5, r=0.1)
        paras = [{"text": title, "size": tsize, "bold": True, "color": tcolor}]
        if sub:
            paras.append({"text": sub, "size": ssize, "color": scolor})
        self.text(x, y, w, h, paras, align="c", anchor="m", pad=0.07)


# ---- measuring -------------------------------------------------------------------------------------

_fonts: dict[tuple[bool, float], ImageFont.FreeTypeFont] = {}


def font(bold: bool, size_pt: float) -> ImageFont.FreeTypeFont:
    key = (bold, round(size_pt * PX / 72, 2))
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(_LIB.format("Bold" if bold else "Regular"), key[1])
    return _fonts[key]


LH = 1.15  # Arial's single line spacing, as a multiple of the font size
BULLET_INDENT = 0.22


def layout_text(op: dict) -> tuple[list[dict], float]:
    """Wrap the paragraphs into lines for the box. Returns (lines, total height in inches)."""
    box_w = op["w"] - 2 * op["pad"]
    lines: list[dict] = []
    total = 0.0
    for p in op["paras"]:
        indent = BULLET_INDENT if p["bullet"] else 0.0
        avail = (box_w - indent) * PX
        tokens: list[tuple[str, bool]] = []
        for txt, b in runs_of(p["text"]):
            for k, word in enumerate(re.split(r"(\s+)", txt)):
                if word:
                    tokens.append((word, b or p["bold"]))
        cur: list[tuple[str, bool]] = []
        cur_w = 0.0
        plines: list[list[tuple[str, bool]]] = []
        for word, b in tokens:
            wl = font(b, p["size"]).getlength(word)
            if word.isspace():
                if cur:
                    cur.append((word, b))
                    cur_w += wl
                continue
            if cur and cur_w + wl > avail:
                while cur and cur[-1][0].isspace():
                    cur.pop()
                plines.append(cur)
                cur, cur_w = [], 0.0
            cur.append((word, b))
            cur_w += wl
        while cur and cur[-1][0].isspace():
            cur.pop()
        plines.append(cur)
        for i, ln in enumerate(plines):
            lh = p["size"] * LH / 72
            lines.append({"runs": ln, "p": p, "first": i == 0, "indent": indent, "h": lh})
            total += lh
        total += p["after"] / 72
    return lines, total


class Deck:
    def __init__(self):
        self.slides: list[Slide] = []

    def add(self, bg: str, notes: str = "") -> Slide:
        s = Slide(bg, notes)
        self.slides.append(s)
        return s

    # ---- preview ---------------------------------------------------------------------------------

    def preview(self, i: int, out: Path) -> list[str]:
        s = self.slides[i]
        img = Image.new("RGB", (round(W * PX), round(H * PX)), rgb(s.bg))
        d = ImageDraw.Draw(img, "RGBA")
        warns: list[str] = []
        for op in s.ops:
            k, a = op.kind, op.kw
            if k in ("rect", "oval"):
                box = [a["x"] * PX, a["y"] * PX, (a["x"] + a["w"]) * PX, (a["y"] + a["h"]) * PX]
                fill = rgb(a["fill"]) if a["fill"] else None
                line = rgb(a["line"]) if a["line"] else None
                lw = max(1, round(a["lw"] * PX / 72))
                if k == "oval":
                    d.ellipse(box, fill=fill, outline=line, width=lw)
                elif a["r"]:
                    d.rounded_rectangle(box, radius=a["r"] * PX, fill=fill, outline=line, width=lw)
                else:
                    d.rectangle(box, fill=fill, outline=line, width=lw)
            elif k == "text":
                lines, total = layout_text(a)
                inner_h = a["h"] - 2 * a["pad"]
                if total > inner_h + 0.02:
                    first = a["paras"][0]["text"][:40]
                    warns.append(f"slide {i + 1}: text overflows its box by {total - inner_h:.2f} in ('{first}')")
                y = a["y"] + a["pad"]
                if a["anchor"] == "m":
                    y += (inner_h - total) / 2
                elif a["anchor"] == "b":
                    y += inner_h - total
                for ln in lines:
                    p = ln["p"]
                    width = sum(font(b, p["size"]).getlength(t) for t, b in ln["runs"]) / PX
                    inner_w = a["w"] - 2 * a["pad"] - ln["indent"]
                    x0 = a["x"] + a["pad"] + ln["indent"]
                    al = p.get("align", a["align"])
                    if al == "c":
                        x0 += (inner_w - width) / 2
                    elif al == "r":
                        x0 += inner_w - width
                    if p["bullet"] and ln["first"]:
                        d.text((a["x"] * PX + a["pad"] * PX + 4, (y + ln["h"] * 0.12) * PX), "•", font=font(False, p["size"]), fill=rgb(p["color"]))
                    cx = x0 * PX
                    for t, b in ln["runs"]:
                        f = font(b, p["size"])
                        d.text((cx, (y + ln["h"] * 0.1) * PX), t, font=f, fill=rgb(p["color"]))
                        cx += f.getlength(t)
                    y += ln["h"]
                    if ln is lines[-1] or lines[lines.index(ln) + 1]["p"] is not p:
                        y += p["after"] / 72
            elif k == "pic":
                im = fit_picture(a["path"], a["w"], a["h"], a["anchor"], a["radius"], a["border"])
                img.paste(im.resize((round(a["w"] * PX), round(a["h"] * PX))), (round(a["x"] * PX), round(a["y"] * PX)), im.resize((round(a["w"] * PX), round(a["h"] * PX))))
            elif k == "arrow":
                d.line([a["x1"] * PX, a["y1"] * PX, a["x2"] * PX, a["y2"] * PX], fill=rgb(a["color"]), width=max(1, round(a["lw"] * PX / 72)))
                if a["head"]:
                    import math

                    ang = math.atan2(a["y2"] - a["y1"], a["x2"] - a["x1"])
                    L, Wd = 0.13, 0.07
                    tip = (a["x2"], a["y2"])
                    p1 = (tip[0] - L * math.cos(ang) + Wd * math.sin(ang), tip[1] - L * math.sin(ang) - Wd * math.cos(ang))
                    p2 = (tip[0] - L * math.cos(ang) - Wd * math.sin(ang), tip[1] - L * math.sin(ang) + Wd * math.cos(ang))
                    d.polygon([(tip[0] * PX, tip[1] * PX), (p1[0] * PX, p1[1] * PX), (p2[0] * PX, p2[1] * PX)], fill=rgb(a["color"]))
            elif k == "chart":
                draw_chart_preview(d, a)
        img.save(out)
        return warns

    # ---- pptx ------------------------------------------------------------------------------------

    def save_pptx(self, path: Path, tmp: Path) -> None:
        from pptx import Presentation
        from pptx.chart.data import CategoryChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
        from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.oxml.ns import qn
        from pptx.util import Emu, Inches, Pt
        from lxml import etree

        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(W), Inches(H)
        blank = prs.slide_layouts[6]
        tmp.mkdir(parents=True, exist_ok=True)

        def col(h):
            return RGBColor.from_string(h)

        for si, s in enumerate(self.slides):
            sl = prs.slides.add_slide(blank)
            sl.background.fill.solid()
            sl.background.fill.fore_color.rgb = col(s.bg)
            if s.notes:
                sl.notes_slide.notes_text_frame.text = s.notes
            for n, op in enumerate(s.ops):
                a = op.kw
                if op.kind in ("rect", "oval"):
                    shp_kind = MSO_SHAPE.OVAL if op.kind == "oval" else (MSO_SHAPE.ROUNDED_RECTANGLE if a.get("r") else MSO_SHAPE.RECTANGLE)
                    sh = sl.shapes.add_shape(shp_kind, Inches(a["x"]), Inches(a["y"]), Inches(a["w"]), Inches(a["h"]))
                    if op.kind == "rect" and a.get("r"):
                        sh.adjustments[0] = min(0.5, a["r"] / min(a["w"], a["h"]))
                    if a["fill"]:
                        sh.fill.solid()
                        sh.fill.fore_color.rgb = col(a["fill"])
                    else:
                        sh.fill.background()
                    if a["line"]:
                        sh.line.color.rgb = col(a["line"])
                        sh.line.width = Pt(a["lw"])
                    else:
                        sh.line.fill.background()
                    sh.shadow.inherit = False
                elif op.kind == "text":
                    tb = sl.shapes.add_textbox(Inches(a["x"]), Inches(a["y"]), Inches(a["w"]), Inches(a["h"]))
                    tf = tb.text_frame
                    tf.word_wrap = True
                    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(a["pad"])
                    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[a["anchor"]]
                    for pi, p in enumerate(a["paras"]):
                        para = tf.paragraphs[0] if pi == 0 else tf.add_paragraph()
                        para.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[p.get("align", a["align"])]
                        para.line_spacing = 1.0
                        para.space_after = Pt(p["after"])
                        if p["bullet"]:
                            pPr = para._p.get_or_add_pPr()
                            pPr.set("marL", str(int(Inches(BULLET_INDENT))))
                            pPr.set("indent", str(-int(Inches(BULLET_INDENT))))
                            bu = etree.SubElement(pPr, qn("a:buChar"))
                            bu.set("char", "•")
                        for txt, b in runs_of(p["text"]):
                            r = para.add_run()
                            r.text = txt
                            r.font.name = FONT
                            r.font.size = Pt(p["size"])
                            r.font.bold = bool(b or p["bold"])
                            r.font.color.rgb = col(p["color"])
                elif op.kind == "pic":
                    im = fit_picture(a["path"], a["w"], a["h"], a["anchor"], a["radius"], a["border"])
                    f = tmp / f"s{si}_{n}.png"
                    im.save(f)
                    sl.shapes.add_picture(str(f), Inches(a["x"]), Inches(a["y"]), Inches(a["w"]), Inches(a["h"]))
                elif op.kind == "arrow":
                    c = sl.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(a["x1"]), Inches(a["y1"]), Inches(a["x2"]), Inches(a["y2"]))
                    c.line.color.rgb = col(a["color"])
                    c.line.width = Pt(a["lw"])
                    if a["head"]:
                        ln = c.line._get_or_add_ln()
                        te = etree.SubElement(ln, qn("a:tailEnd"))
                        te.set("type", "triangle")
                elif op.kind == "chart":
                    cd = CategoryChartData()
                    cd.categories = a["cats"]
                    for name, vals, _ in a["series"]:
                        cd.add_series(name, vals)
                    gf = sl.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(a["x"]), Inches(a["y"]), Inches(a["w"]), Inches(a["h"]), cd)
                    ch = gf.chart
                    ch.font.name = FONT
                    ch.font.size = Pt(11)
                    ch.font.color.rgb = col("B6C2D6")
                    ch.has_legend = len(a["series"]) > 1
                    if ch.has_legend:
                        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
                        ch.legend.include_in_layout = False
                        ch.legend.font.size = Pt(11)
                        ch.legend.font.color.rgb = col("D5DEEC")
                    plot = ch.plots[0]
                    plot.gap_width = 70
                    plot.overlap = -5
                    plot.has_data_labels = True
                    dl = plot.data_labels
                    dl.number_format = a["fmt"]
                    dl.number_format_is_linked = False
                    dl.position = XL_LABEL_POSITION.OUTSIDE_END
                    dl.font.size = Pt(11)
                    dl.font.bold = True
                    dl.font.color.rgb = col("F1F5F9")
                    for ser, (_, _, hexc) in zip(plot.series, a["series"]):
                        ser.format.fill.solid()
                        ser.format.fill.fore_color.rgb = col(hexc)
                    va = ch.value_axis
                    va.minimum_scale, va.maximum_scale = 0, a["ymax"]
                    va.has_major_gridlines = True
                    va.major_gridlines.format.line.color.rgb = col("24324A")
                    va.format.line.fill.background()
                    va.tick_labels.font.size = Pt(10)
                    va.tick_labels.font.color.rgb = col("94A3B8")
                    va.tick_labels.number_format = a["fmt"] if not a["pct"] else '0"%"'
                    va.tick_labels.number_format_is_linked = False
                    ca = ch.category_axis
                    ca.format.line.color.rgb = col("475569")
                    ca.tick_labels.font.size = Pt(11)
                    ca.tick_labels.font.color.rgb = col("D5DEEC")
        prs.save(path)


# ---- pictures --------------------------------------------------------------------------------------

_pic_cache: dict[tuple, Image.Image] = {}


def fit_picture(path: str, w: float, h: float, anchor: str, radius: float, border: str | None) -> Image.Image:
    """Crop a screenshot to the box (cover), round its corners, draw a thin border. RGBA."""
    key = (path, w, h, anchor, radius, border)
    if key in _pic_cache:
        return _pic_cache[key]
    im = Image.open(path).convert("RGB")
    target = w / h
    iw, ih = im.size
    if iw / ih > target:  # too wide: crop the sides
        nw = round(ih * target)
        x0 = (iw - nw) // 2
        im = im.crop((x0, 0, x0 + nw, ih))
    else:  # too tall: crop top/bottom
        nh = round(iw / target)
        y0 = 0 if anchor == "t" else (ih - nh) // 2
        im = im.crop((0, y0, iw, y0 + nh))
    out_w = 1100
    im = im.resize((out_w, round(out_w / target)), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", im.size, 0)
    rad = round(radius / w * out_w)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], radius=rad, fill=255)
    im.putalpha(mask)
    if border:
        ImageDraw.Draw(im).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], radius=rad, outline=rgb(border) + (255,), width=3)
    _pic_cache[key] = im
    return im


def draw_chart_preview(d: ImageDraw.ImageDraw, a: dict) -> None:
    x, y, w, h = a["x"] * PX, a["y"] * PX, a["w"] * PX, a["h"] * PX
    legend_h = 0.4 * PX if len(a["series"]) > 1 else 0
    left, bottom, top = 0.5 * PX, 0.4 * PX, 0.3 * PX
    px0, py0 = x + left, y + top
    pw, ph = w - left - 0.1 * PX, h - top - bottom - legend_h
    for g in range(0, 5):
        gy = py0 + ph - ph * g / 4
        d.line([px0, gy, px0 + pw, gy], fill=rgb("24324A"), width=1)
        v = a["ymax"] * g / 4
        label = f"{v:.0f}%" if a["pct"] else f"{v:.1f}"
        d.text((x + 4, gy - 7), label, font=font(False, 9), fill=rgb("94A3B8"))
    ncat, nser = len(a["cats"]), len(a["series"])
    gw = pw / ncat
    bw = gw * 0.78 / nser
    for ci, cat in enumerate(a["cats"]):
        gx = px0 + ci * gw + gw * 0.11
        for si, (name, vals, hexc) in enumerate(a["series"]):
            bh = ph * min(vals[ci], a["ymax"]) / a["ymax"]
            bx = gx + si * bw
            d.rectangle([bx, py0 + ph - bh, bx + bw - 3, py0 + ph], fill=rgb(hexc))
            label = f"{vals[ci]:.0f}%" if a["pct"] else f"{vals[ci]:.2f}"
            f = font(True, 11)
            d.text((bx + (bw - 3 - f.getlength(label)) / 2, py0 + ph - bh - 17), label, font=f, fill=rgb("F1F5F9"))
        f = font(False, 11)
        d.text((px0 + ci * gw + (gw - f.getlength(cat)) / 2, py0 + ph + 6), cat, font=f, fill=rgb("D5DEEC"))
    if legend_h:
        lx = x + w / 2 - sum(font(False, 11).getlength(n) + 40 for n, _, _ in a["series"]) / 2
        ly = y + h - 0.3 * PX
        for name, _, hexc in a["series"]:
            d.rectangle([lx, ly + 3, lx + 12, ly + 15], fill=rgb(hexc))
            d.text((lx + 18, ly), name, font=font(False, 11), fill=rgb("D5DEEC"))
            lx += font(False, 11).getlength(name) + 40
