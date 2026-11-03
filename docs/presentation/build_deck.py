"""Builds docs/presentation/GenAI-VMS-overview.pptx (12 slides, native editable shapes and charts).

    python docs/presentation/build_deck.py [preview-dir]     # needs python-pptx and Pillow

With a preview directory it also writes slide-NN.png renders (Pillow, Liberation Sans) and prints
any text that would overflow its box. The screenshots in img/ are of the running application.
"""

from __future__ import annotations

import sys
from pathlib import Path

from deckkit import Deck

HERE = Path(__file__).resolve().parent
IMG = HERE / "img"

BG, CARD, CARD2, LINE = "0B1220", "131C2E", "182338", "2A3A55"
TEXT, SOFT, MUTED = "F1F5F9", "C9D5E6", "93A4BC"
TEAL, BLUE, ORANGE, PURPLE, GREEN, RED, AMBER = "2DD4BF", "60A5FA", "FB923C", "C084FC", "4ADE80", "F87171", "FBBF24"
BLUE_F, GREEN_F, ORANGE_F, PURPLE_F, TEAL_F, AMBER_F = "12284A", "0E3B34", "3A2312", "2D1B4A", "0C3A3C", "3A2E0E"
TOTAL = 12

deck = Deck()


def chrome(s, n: int, kicker: str, title: str) -> None:
    s.rect(0.6, 0.38, 0.5, 0.06, fill=TEAL)
    s.text(0.54, 0.46, 9, 0.3, kicker.upper(), size=11.5, color=TEAL, bold=True)
    s.text(0.54, 0.74, 12.2, 0.7, title, size=29, bold=True)
    s.text(0.54, 7.06, 6, 0.28, "GenAI-VMS  ·  reasoning-based video analytics for CCTV", size=10, color=MUTED)
    s.text(11.7, 7.06, 1.05, 0.28, f"{n} / {TOTAL}", size=10, color=MUTED, align="r")


def bullets(s, x, y, w, h, items, size=13, color=SOFT, after=6):
    s.text(x, y, w, h, [{"text": t, "bullet": True, "after": after} for t in items], size=size, color=color)


def circle_no(s, x, y, n, color=TEAL, d=0.4):
    s.oval(x, y, d, d, fill=color)
    s.text(x, y, d, d, str(n), size=13, bold=True, color="0B1220", align="c", anchor="m", pad=0)


# ---- 1 · title -----------------------------------------------------------------------------------
s = deck.add(
    BG,
    "Open with the one-sentence version: GenAI-VMS turns hours of CCTV into something you can search, question and "
    "read, on a single laptop. Say the three verbs on the slide: search in plain words, understand an incident phase "
    "by phase, ask questions and get cited answers. The picture on the right is the real application running on the "
    "demo footage. Today's walk-through goes from the problem, through the architecture, to what we measured and what "
    "we did not manage.",
)
s.rect(0, 0, 0.22, 7.5, fill=TEAL)
s.text(0.9, 1.35, 6, 0.4, "INTERNSHIP PROJECT  ·  2026", size=13, color=TEAL, bold=True)
s.text(0.9, 1.85, 6, 1.1, "GenAI-VMS", size=60, bold=True)
s.text(0.9, 3.0, 5.7, 1.0, "Reasoning-based video analytics for CCTV", size=26, color=SOFT)
s.text(
    0.9,
    4.15,
    5.5,
    1.3,
    ["Search what happened in plain words", "Understand an incident phase by phase", "Ask questions, get answers that cite their evidence"],
    size=15,
    color=MUTED,
)
s.text(0.9, 6.3, 5.5, 0.4, "Divyansh  ·  Jatin", size=15, bold=True)
s.pic(IMG / "live.jpg", 6.75, 1.45, 6.05, 3.19, radius=0.14)
for i, (big, small, c) in enumerate([("4 GB", "GPU is all it needs", TEAL), ("0.22 s", "fast search, median", BLUE), ("100 %", "models can run locally", PURPLE)]):
    x = 6.75 + i * 2.05
    s.card(x, 4.95, 1.95, 1.35, CARD, line=LINE)
    s.text(x, 5.02, 1.95, 0.7, big, size=28, bold=True, color=c, align="c", anchor="m")
    s.text(x, 5.68, 1.95, 0.5, small, size=11.5, color=MUTED, align="c")

# ---- 2 · problem ---------------------------------------------------------------------------------
s = deck.add(
    BG,
    "Start with the human problem. A site with nine cameras records nine hours of video every hour and nobody can watch "
    "it. Finding one moment, 'the man in the red jacket yesterday evening', means scrubbing. Our idea has three steps: "
    "understand every clip once, store the result as data, and let language models read that data instead of the "
    "pixels. Finish by naming the constraint: all of it runs on one laptop with a 4 GB GPU, built in six weeks by two people.",
)
chrome(s, 2, "01 · The problem", "Nobody can watch every camera")
s.card(0.6, 1.6, 4.5, 3.55, CARD, line=RED, lw=1.5)
s.text(0.85, 1.72, 4.0, 0.4, "Today", size=18, bold=True, color=RED)
bullets(
    s,
    0.85,
    2.2,
    4.0,
    2.9,
    [
        "Nine cameras record nine hours of video every hour",
        "Finding one moment means scrubbing for hours",
        "Reviewing yesterday means watching it again",
        "An alert says something happened, not why",
        "One tired person is the search engine",
    ],
    size=14,
)
s.arrow(5.25, 3.4, 5.75, 3.4, color=TEAL, lw=3)
tiles = [
    ("Understands every clip", "people, objects, tracks, zones", GREEN_F, GREEN),
    ("Searches in plain words", "“a person carrying a suitcase”", BLUE_F, BLUE),
    ("Raises and checks alerts", "rules first, then a vision model", ORANGE_F, ORANGE),
    ("Writes cited reports", "every claim points at evidence", PURPLE_F, PURPLE),
]
s.text(5.9, 1.6, 6.8, 0.4, "With GenAI-VMS", size=18, bold=True, color=TEAL)
for i, (t, sub, f, c) in enumerate(tiles):
    x, y = 5.9 + (i % 2) * 3.5, 2.12 + (i // 2) * 1.55
    s.node(x, y, 3.3, 1.4, t, sub, f, c, tsize=15, ssize=11.5)
s.card(0.6, 5.4, 12.13, 0.95, CARD2, line=LINE)
for i, (t, c) in enumerate([("Understand each clip once", GREEN), ("Store it as searchable data", BLUE), ("Let models read the data", PURPLE)]):
    x = 0.85 + i * 4.0
    s.text(x, 5.4, 3.5, 0.95, t, size=15, bold=True, color=c, align="c", anchor="m")
    if i < 2:
        s.arrow(x + 3.55, 5.87, x + 3.95, 5.87, color=MUTED)
s.text(0.6, 6.5, 12.13, 0.4, "Built to run on one laptop: 4 GB GPU, local models, no cloud needed.  Six weeks, two builders.", size=12.5, color=MUTED, align="c")

# ---- 3 · architecture ----------------------------------------------------------------------------
s = deck.add(
    BG,
    "This is the whole system. Read it top to bottom. Lane one records video: cameras into MediaMTX, ingestion cuts it "
    "into ten-second segments and stores them in MinIO. Lane two understands it: perception detects and tracks "
    "objects and writes a digital twin, a JSON description of the clip, which the indexer files into Postgres and "
    "Qdrant. Lane three notices things: rules propose events, a vision model checks them, correlation links cameras, "
    "alerts reach the operator. Lane four is the GenAI part: search, incident reasoning, the assistant, reports. "
    "Everything that needs a model goes through one gateway. Kafka carries small messages with links, never video.",
)
chrome(s, 3, "02 · Architecture", "The system on one page")
lanes = [
    ("1 · Get the video in", "record and store", BLUE, BLUE_F, [("Cameras", "RTSP or simulator"), ("MediaMTX", "live re-broadcast"), ("Ingestion", "10 s segments + keyframes"), ("MinIO", "video + pictures")]),
    ("2 · Understand it", "the digital twin", GREEN, GREEN_F, [("Perception", "YOLO11 · ByteTrack · SigLIP 2"), ("Digital twin", "one JSON per 10 s clip"), ("Indexer", "files it for search"), ("Postgres + Qdrant", "facts + meaning vectors")]),
    ("3 · Notice and check", "events and alerts", ORANGE, ORANGE_F, [("Events", "6 rules on the twin"), ("VLM gate", "“is it real?” yes / no / unsure"), ("Correlation", "links cameras by map + time"), ("Alerts", "open → ack → resolved")]),
    ("4 · Explain and answer", "the GenAI part", PURPLE, PURPLE_F, [("Search", "fast · reason · image"), ("Reasoning", "phases + cited report"), ("Assistant", "chat, 7 fixed tools"), ("Reports", "daily + incident PDF"), ("Timeline", "lanes + cases")]),
]
for li, (name, sub, c, f, boxes) in enumerate(lanes):
    y = 1.5 + li * 1.2
    s.rect(0.6, y, 2.35, 1.0, fill=c, r=0.1)
    s.text(0.6, y, 2.35, 1.0, [{"text": name, "size": 14, "bold": True, "color": "0B1220"}, {"text": sub, "size": 11, "color": "1E293B"}], align="c", anchor="m")
    if li < 3:
        s.arrow(1.775, y + 1.0, 1.775, y + 1.2, color=MUTED, lw=2)
    n = len(boxes)
    bw, gap = (2.08, 0.4) if n == 4 else (1.7, 0.26)
    for bi, (t, sb) in enumerate(boxes):
        x = 3.2 + bi * (bw + gap)
        s.node(x, y + 0.11, bw, 0.78, t, sb, f, c, tsize=13, ssize=10)
        if bi < n - 1 and li < 3:
            s.arrow(x + bw + 0.04, y + 0.5, x + bw + gap - 0.04, y + 0.5, color=MUTED)
s.node(0.6, 6.32, 5.9, 0.62, "LLM gateway: every model call goes through it", "Ollama (local) · Gemini / Groq (cloud) · cache · validation", CARD2, PURPLE, tsize=12.5, ssize=10)
s.node(6.83, 6.32, 5.9, 0.62, "API: login, roles, live push  →  React dashboard", "FastAPI · WebSocket alerts · presigned video links", CARD2, TEAL, tsize=12.5, ssize=10)

# ---- 4 · clip to data ----------------------------------------------------------------------------
s = deck.add(
    BG,
    "Follow one ten-second clip. Ingestion cuts the live stream into segments and keeps one picture per second. "
    "Perception finds people, bags and vehicles, gives each one a track id so we can follow it, and also computes "
    "picture embeddings. All of that is written as one JSON file per segment, the digital twin. The indexer files the facts "
    "in Postgres and the meaning vectors in Qdrant. The screenshot shows the twin drawn over the playback: the boxes and "
    "ids are not painted on the video, they come from the data. Design rule: Kafka messages carry s3:// links, never video, "
    "and consumers are idempotent, so a crashed service can simply re-read and re-write.",
)
chrome(s, 4, "03 · From video to data", "How a 10-second clip becomes data")
steps = [
    ("Ingest", BLUE, BLUE_F, ["Camera video arrives over RTSP", "Cut into 10 s segments", "One keyframe per second", "Announced on Kafka (segment.v1)"]),
    ("Perceive", GREEN, GREEN_F, ["YOLO11 finds people, bags, vehicles", "ByteTrack gives each an id", "Zones and attributes", "SigLIP 2 makes picture vectors"]),
    ("Digital twin", ORANGE, ORANGE_F, ["One JSON per 10 s segment", "Objects, tracks, zones, vectors", "Stands in for the video in most questions", "Drawn over playback"]),
    ("Index", PURPLE, PURPLE_F, ["Facts go to PostgreSQL", "Meaning vectors go to Qdrant", "Captions join a text index", "Searchable within seconds"]),
]
for i, (t, c, f, items) in enumerate(steps):
    x = 0.6 + i * 3.09
    s.card(x, 1.5, 2.85, 2.1, f, line=c, lw=1.5)
    circle_no(s, x + 0.15, 1.62, i + 1, color=c)
    s.text(x + 0.6, 1.62, 2.2, 0.4, t, size=16, bold=True, color=c, anchor="m")
    bullets(s, x + 0.12, 2.12, 2.65, 1.45, items, size=11.5, after=2)
    if i < 3:
        s.arrow(x + 2.87, 2.55, x + 3.07, 2.55, color=MUTED, lw=2)
s.pic(IMG / "playback.jpg", 0.6, 3.78, 6.2, 2.99, radius=0.12)
s.text(0.6, 6.74, 6.3, 0.3, "Playback: the boxes and ids are the digital twin, drawn over the video", size=10.5, color=MUTED)
s.text(7.3, 3.85, 5.4, 0.4, "Why this design", size=17, bold=True, color=TEAL)
bullets(
    s,
    7.3,
    4.3,
    5.43,
    2.5,
    [
        "**Understand once, reuse everywhere:** search, events and reports all read the twin",
        "**No video on Kafka:** messages are small and carry s3:// links",
        "**Safe restarts:** consumers validate, write idempotently, then commit",
        "**966 MB of GPU** for the whole perception step",
    ],
    size=13.5,
)

# ---- 5 · events ----------------------------------------------------------------------------------
s = deck.add(
    BG,
    "Events work in two stages because the two things we need are in tension: cheap and thorough, versus accurate. "
    "Six simple rules run on every segment's twin and produce candidates. Then a vision model looks at the actual "
    "pictures and answers yes, no or unsure. Yes becomes a verified event and an alert; no is kept for audit but never "
    "shown. In today's replay of three bus-station cameras the rules produced 25 candidates; the gate verified 10 and "
    "rejected 15 as false alarms. Alerts have a lifecycle, open, acknowledged, resolved, and are pushed live over a WebSocket.",
)
chrome(s, 5, "04 · Events and alerts", "Events: cheap rules, then a vision model checks")
chain = [("Digital twin", "per 10 s clip", GREEN_F, GREEN), ("6 rules", "cheap, every segment", ORANGE_F, ORANGE), ("Candidate", "“something may be wrong”", ORANGE_F, ORANGE), ("VLM gate", "looks at the pictures", PURPLE_F, PURPLE), ("Verdict", "yes · no · unsure", PURPLE_F, PURPLE), ("Alert", "pushed live", ORANGE_F, ORANGE)]
for i, (t, sb, f, c) in enumerate(chain):
    x = 0.6 + i * 2.07
    s.node(x, 1.5, 1.8, 1.0, t, sb, f, c, tsize=13.5, ssize=10.5)
    if i < 5:
        s.arrow(x + 1.82, 2.0, x + 2.05, 2.0, color=MUTED)
s.pic(IMG / "event.jpg", 0.6, 2.85, 5.4, 3.44, radius=0.12)
s.text(0.6, 6.33, 5.4, 0.5, "One event: the clip, its keyframes, the model's caption and its confidence", size=10.5, color=MUTED)
s.card(6.35, 2.85, 6.38, 1.2, CARD, line=LINE)
s.text(6.55, 2.9, 6.0, 0.35, "Six rules", size=15, bold=True, color=ORANGE)
s.text(6.55, 3.27, 6.0, 0.75, "Loitering  ·  Crowding  ·  Abandoned object  ·  Running  ·  Intrusion in a restricted zone  ·  Intrusion after hours", size=12.5, color=SOFT)
s.card(6.35, 4.2, 6.38, 1.55, CARD, line=LINE)
s.text(6.55, 4.25, 6.0, 0.35, "The gate's verdict", size=15, bold=True, color=PURPLE)
s.text(
    6.55,
    4.62,
    6.0,
    1.3,
    [
        {"text": "**yes**  →  verified: becomes an alert", "after": 4},
        {"text": "**no**  →  rejected: kept for audit, never shown", "after": 4},
        {"text": "**unsure or model down**  →  skipped: alerts anyway, marked unchecked"},
    ],
    size=12.5,
    color=SOFT,
)
s.card(6.35, 5.95, 6.38, 0.8, TEAL_F, line=TEAL)
s.text(6.5, 5.95, 6.1, 0.8, "Replay on 3 cameras: **25 candidates → 10 verified** (3 high severity), **15 rejected** as false alarms", size=12.5, anchor="m")

# ---- 6 · incidents -------------------------------------------------------------------------------
s = deck.add(
    BG,
    "An event tells you something happened; an incident report tells you what happened and why. First, correlation "
    "groups events from different cameras into one story using a camera map: overlap links for two views of one area, "
    "transit links for walking from one camera to the next. When an operator clicks Analyse, a vision model places five "
    "phases on the timeline: baseline, precursor, escalation, action, aftermath. For each phase it reads two frames and "
    "answers questions from a question bank; every answer becomes evidence with an id. Then a language model writes the report, "
    "and every claim must cite evidence ids; a claim without a citation is dropped. The report also states what it cannot tell, "
    "and records which model wrote it and how long each step took.",
)
chrome(s, 6, "05 · Incident reasoning", "Incidents: what happened, phase by phase")
phases = [("Baseline", "normal, before", BLUE_F, BLUE), ("Precursor", "something starts", TEAL_F, TEAL), ("Escalation", "it builds", AMBER_F, AMBER), ("Action", "the event itself", ORANGE_F, ORANGE), ("Aftermath", "what follows", "3A1616", RED)]
for i, (t, sb, f, c) in enumerate(phases):
    s.node(0.6 + i * 2.45, 1.5, 2.3, 0.78, t, sb, f, c, tsize=14, ssize=10.5)
rows = [
    ("Link across cameras", "A camera map (overlap or transit links) and a time window group events into one incident."),
    ("Analyse", "A click, or automatic for severe events. A vision model places the five phases on the timeline."),
    ("Read each phase", "Two frames plus questions from a question bank. Every answer becomes evidence with an id."),
    ("Write the report", "Every claim must cite evidence ids; uncited claims are dropped. The report says what it cannot tell."),
]
for i, (t, d) in enumerate(rows):
    y = 2.55 + i * 1.05
    circle_no(s, 0.6, y + 0.05, i + 1)
    s.text(1.15, y, 5.6, 0.35, t, size=14.5, bold=True, color=TEAL)
    s.text(1.15, y + 0.34, 5.6, 0.7, d, size=12, color=SOFT)
s.pic(IMG / "incident.jpg", 7.2, 2.55, 5.53, 3.69, radius=0.12, anchor="t")
s.text(7.2, 6.3, 5.53, 0.6, "The report: phase timeline, per-phase evidence chips, “What this report cannot tell”, PDF export", size=10.5, color=MUTED)

# ---- 7 · search ----------------------------------------------------------------------------------
s = deck.add(
    BG,
    "Search has two speeds on purpose. Fast mode turns the sentence into a vector and a text query, searches pictures and "
    "captions, and merges the two rankings with Reciprocal Rank Fusion, in about a fifth of a second. Reason mode takes the "
    "top thirty candidates and lets a language model re-read each one, score it, and say what the records could not confirm; "
    "that takes around fifteen seconds on this laptop. The screenshot shows 'Why this result'. You can also search by image, "
    "find similar to a box you draw on a paused frame, and see object outlines. In our 36-query benchmark on real footage, "
    "reason mode finds the right clip in the top ten for 67 percent of queries, fast mode 56 percent, random 24 percent.",
)
chrome(s, 7, "06 · Search", "Search in plain words")
s.card(0.6, 1.5, 5.95, 1.6, CARD, line=TEAL, lw=1.5)
s.text(0.8, 1.56, 5.6, 0.4, "FAST  ·  about 0.2 s", size=16, bold=True, color=TEAL)
bullets(s, 0.8, 1.98, 5.6, 1.4, ["Sentence → vector (SigLIP 2) and a text query", "Pictures and captions searched, merged with Reciprocal Rank Fusion", "Hits within 10 s on a camera become one window"], size=12, after=3)
s.card(6.78, 1.5, 5.95, 1.6, CARD, line=PURPLE, lw=1.5)
s.text(6.98, 1.56, 5.6, 0.4, "REASON  ·  about 15 s", size=16, bold=True, color=PURPLE)
bullets(s, 6.98, 1.98, 5.6, 1.4, ["Top 30 fast candidates, re-read by a language model", "Scores 0–1 and says what it could not confirm", "Final score: 40 % fused rank + 60 % model"], size=12, after=3)
s.pic(IMG / "search.jpg", 0.6, 3.3, 7.2, 3.15, radius=0.12, anchor="t")
s.text(0.6, 6.5, 7.2, 0.3, "Reason mode: each hit says why it matched and what the records could not confirm", size=10.5, color=MUTED)
s.text(8.1, 3.3, 4.6, 0.4, "More ways in", size=16, bold=True, color=TEAL)
bullets(
    s,
    8.1,
    3.78,
    4.63,
    2.2,
    [
        "**Search by image:** upload a photo or a frame",
        "**Find similar here:** draw a box on a paused frame",
        "**Object outlines:** 1.3 s first time, 9 ms cached",
        "**Every hit opens** the recording, event or report",
    ],
    size=12.5,
    after=4,
)
s.card(8.1, 5.85, 4.63, 0.85, TEAL_F, line=TEAL)
s.text(8.23, 5.85, 4.4, 0.85, "Right clip in the top 10 on real footage: **67 %** reason, **56 %** fast, 24 % random", size=12, anchor="m")

# ---- 8 · assistant, reports, timeline ------------------------------------------------------------
s = deck.add(
    BG,
    "Three more ways to use the same data. The assistant answers questions in chat but can only use seven fixed, "
    "parameterised lookups, at most four per answer, so it never writes SQL and cannot invent a query. Every answer shows "
    "what it looked up and cites real records. The daily report takes its facts from fixed queries; the language model "
    "only writes the narrative, and every number in it is checked against the facts. The timeline shows a lane per camera, "
    "lets you select a period and play all cameras in sync from one playhead; cases collect evidence for an investigation.",
)
chrome(s, 8, "07 · Ask, report, review", "Ask, report, review")
cols = [
    ("Assistant", "assistant.jpg", "t", ["Chat about the cameras in plain language", "Seven fixed lookups, at most four per answer: it never writes SQL", "Shows what it looked up; cites real records"]),
    ("Daily report", "report.jpg", "t", ["Facts come from fixed queries; the model only writes the narrative", "Every number in it is checked against the facts", "Written each morning, or on demand; PDF export"]),
    ("Timeline and cases", "timeline.jpg", "t", ["A lane per camera: events and incident reports", "Select a period: zoom, search inside it, or play all cameras in sync", "Save events, reports and footage moments to a case"]),
]
for i, (t, img, anc, items) in enumerate(cols):
    x = 0.6 + i * 4.12
    s.pic(IMG / img, x, 1.55, 3.89, 2.75, radius=0.12, anchor=anc)
    s.text(x, 4.45, 3.89, 0.4, t, size=17, bold=True, color=TEAL)
    bullets(s, x, 4.88, 3.89, 2.1, items, size=13.5, after=6)

# ---- 9 · GenAI machinery -------------------------------------------------------------------------
s = deck.add(
    BG,
    "The hard constraint is the 4 GB GPU. Two ideas make it work. First, the LLM gateway: no service calls a model "
    "directly. It asks for a task by name, the registry says which model serves that task in the current profile, local, "
    "hybrid or cloud, and the gateway adds caching, schema validation with retry, fallbacks and provenance. Second, the GPU "
    "lease, the 'one chair' idea: only one heavy model sits on the GPU at a time and a Redis lease decides who. We even "
    "fine-tuned a vision model with LoRA on the same card; it took about fifty minutes. The table is what each model costs on this laptop.",
)
chrome(s, 9, "08 · The GenAI machinery", "GenAI on a 4 GB laptop GPU")
flow = [("1 · A task name", "e.g. phase_tg, search_rerank, daily_narrative"), ("2 · The registry", "config/models.yaml: task → model per profile"), ("3 · A profile", "local (Ollama) · hybrid · cloud (Gemini, Groq)"), ("4 · The call", "cache · schema check + retry · fallbacks · provenance")]
for i, (t, sb) in enumerate(flow):
    y = 1.5 + i * 1.33
    s.node(0.6, y, 3.5, 0.95, t, sb, PURPLE_F, PURPLE, tsize=14, ssize=11)
    if i < 3:
        s.arrow(2.35, y + 0.97, 2.35, y + 1.31, color=MUTED, lw=2)
s.text(4.35, 1.5, 2.55, 0.4, "Rules of the road", size=15, bold=True, color=TEAL)
bullets(s, 4.35, 1.95, 2.6, 4.4, ["Nothing calls a model directly", "Structured answers are validated and retried", "Prompts are versioned files", "Every output keeps provenance: model, prompt, latency"], size=13, after=12)
s.card(7.25, 1.5, 5.48, 1.5, CARD, line=ORANGE, lw=1.5)
s.text(7.45, 1.55, 5.1, 0.4, "The GPU lease: one chair", size=16, bold=True, color=ORANGE)
s.text(7.45, 1.95, 5.1, 1.3, "Only one heavy model sits on the GPU at a time. A Redis lease (30 s, renewed while working, 900 s hard limit) decides who; everyone else waits or degrades.", size=12.5, color=SOFT)
hdr_y = 3.2
cw = [1.95, 1.7, 1.83]
cx = [7.25, 7.25 + cw[0], 7.25 + cw[0] + cw[1]]
s.rect(7.25, hdr_y, 5.48, 0.36, fill=LINE, r=0.06)
for x, w, t in zip(cx, cw, ["Model", "Job", "On this laptop"]):
    s.text(x, hdr_y, w, 0.36, t, size=11, bold=True, color=TEAL, anchor="m", pad=0.1)
trows = [
    ("YOLO11 + ByteTrack", "detect and track", "resident"),
    ("SigLIP 2", "picture + text vectors", "966 MB with YOLO"),
    ("qwen2.5:3b", "text reasoning", "0.25 s warm"),
    ("qwen2.5vl:3b", "looks at frames", "3.1 / 5.4 / 11 s for 1 / 2 / 4 images"),
    ("Qwen2.5-VL-3B + LoRA", "fine-tuned phase model", "trained on this GPU in ~50 min"),
]
for i, row in enumerate(trows):
    y = hdr_y + 0.42 + i * 0.66
    s.rect(7.25, y, 5.48, 0.61, fill=CARD if i % 2 == 0 else CARD2, r=0.05)
    for x, w, t in zip(cx, cw, row):
        s.text(x, y, w, 0.61, t, size=10.5, color=TEXT if x == cx[0] else SOFT, bold=x == cx[0], anchor="m", pad=0.1)

# ---- 10 · platform -------------------------------------------------------------------------------
s = deck.add(
    BG,
    "What makes it more than a demo. Reliability: every Kafka consumer validates, writes idempotently, then commits; failures retry "
    "and then go to a dead-letter queue. We run a chaos test and every invariant held. And the rule is degrade, don't die: if the "
    "language model is down, live view, playback and fast search keep working. Security: JWT login, three roles checked on every "
    "request, rate limits, video links that expire in fifteen minutes, an audit log, and no face recognition by design. Delivery: "
    "Docker Compose profiles, Kubernetes manifests validated but never applied to a cluster, Prometheus and Grafana, about three thousand tests. "
    "The strip at the bottom is the stack.",
)
chrome(s, 10, "09 · Platform", "Reliable, secure, deployable")
cols = [
    ("Reliable", BLUE, BLUE_F, ["Consumers: validate → idempotent write → commit", "Failures retry, then go to a dead-letter queue", "Language model down? Live view, playback and fast search keep working", "A chaos test: every invariant held"]),
    ("Secure", ORANGE, ORANGE_F, ["JWT login; roles admin, operator, viewer checked on every request", "Rate limits on login, search, assistant", "Video links are presigned and expire in 15 minutes", "Audit log; no face recognition by design"]),
    ("Deployable", GREEN, GREEN_F, ["Docker Compose profiles: infra, core, perception, genai, obs", "Kubernetes manifests validated, not yet applied to a cluster", "Prometheus and Grafana", "About 3,000 tests; versioned contracts with fixtures"]),
]
for i, (t, c, f, items) in enumerate(cols):
    x = 0.6 + i * 4.12
    s.card(x, 1.5, 3.89, 3.2, f, line=c, lw=1.5)
    s.text(x + 0.2, 1.58, 3.5, 0.45, t, size=18, bold=True, color=c)
    bullets(s, x + 0.2, 2.1, 3.52, 2.55, items, size=13, after=7)
stack = [
    ("Video", "MediaMTX  ·  FFmpeg  ·  MinIO (S3)"),
    ("Messaging and data", "Kafka  ·  PostgreSQL  ·  Qdrant  ·  Redis"),
    ("AI", "YOLO11  ·  ByteTrack  ·  SigLIP 2  ·  Qwen2.5-VL  ·  Ollama  ·  LoRA"),
    ("Apps and ops", "Python 3.11  ·  FastAPI  ·  React + Vite + Tailwind  ·  Docker Compose  ·  Kubernetes"),
]
for i, (k, v) in enumerate(stack):
    y = 4.95 + i * 0.5
    s.text(0.6, y, 2.4, 0.45, k.upper(), size=11.5, bold=True, color=TEAL, anchor="m")
    s.text(3.0, y, 9.7, 0.45, v, size=14, color=SOFT, anchor="m")

# ---- 11 · results --------------------------------------------------------------------------------
s = deck.add(
    BG,
    "Everything on this slide was measured, not estimated. Top row: fast search answers in 0.22 seconds at the median, reason "
    "search in about 15 seconds, the whole perception step fits in 966 MB of GPU memory, and we have about three thousand automated tests. "
    "Left chart: on 36 plain-language queries over real MEVA footage, how often the right clip appears in the top 1, 5 or 10 results; "
    "reason mode beats fast mode, which beats random. Right chart: the assistant's objective checks, whether it chose the right tool, "
    "camera and day, before and after we fixed its routing. The October real-footage run is the last line: the gate verified all thirty "
    "loitering candidates and rejected all nine doorway intrusions.",
)
chrome(s, 11, "10 · Results", "What we measured")
stats = [("0.22 s", "fast search, median", TEAL), ("15.5 s", "reason search, median", PURPLE), ("966 MB", "GPU memory for perception", BLUE), ("3,000+", "automated tests", GREEN)]
for i, (big, lab, c) in enumerate(stats):
    x = 0.6 + i * 3.09
    s.card(x, 1.5, 2.85, 1.25, CARD, line=LINE)
    s.text(x, 1.55, 2.85, 0.75, big, size=34, bold=True, color=c, align="c", anchor="m")
    s.text(x, 2.28, 2.85, 0.4, lab, size=12, color=MUTED, align="c")
s.text(0.6, 3.0, 6.2, 0.4, "Does search find the right clip? (36 queries, real footage)", size=13.5, bold=True)
s.chart(0.6, 3.38, 6.2, 3.5, ["top 1", "top 5", "top 10"], [("random", [0.03, 0.13, 0.24], "64748B"), ("fast mode", [0.14, 0.36, 0.56], BLUE), ("reason mode", [0.22, 0.39, 0.67], PURPLE)], ymax=0.8)
s.text(7.1, 3.0, 5.6, 0.4, "Assistant lookups: baseline → after routing fixes", size=13.5, bold=True)
s.chart(7.1, 3.38, 5.63, 2.55, ["right tool", "right camera", "right day"], [("before", [78, 28, 0], "64748B"), ("after", [100, 100, 100], TEAL)], ymax=100, fmt="0", pct=True)
s.card(7.1, 6.05, 5.63, 0.85, CARD2, line=LINE)
s.text(7.25, 6.05, 5.35, 0.85, "Real-footage run (October): **30 of 30** loitering candidates verified, **9 of 9** doorway intrusions rejected by the gate", size=12, anchor="m")

# ---- 12 · limits and next ------------------------------------------------------------------------
s = deck.add(
    BG,
    "End with honesty; it is a strength. The fine-tuned phase model scored mIoU 0.354 against 0.274 for the untrained model, but "
    "the entire gain is on labels that were made by a rule; on labels a person made there is no measurable gain, so we do not claim "
    "it understands phases better. The cloud VM and Kubernetes deployments are written and validated but never run on real infrastructure. "
    "A clean retrieval ablation and the operator usability study are not done. Cross-camera linking uses time and the camera map, never faces "
    "or appearance. Next steps are on the right. Close by inviting questions, and mention the demo video, study guide and source in the repository.",
)
chrome(s, 12, "11 · Honest limits", "Honest limits and next steps")
s.card(0.6, 1.5, 6.0, 3.95, AMBER_F, line=AMBER, lw=1.5)
s.text(0.85, 1.58, 5.5, 0.45, "What we did not manage", size=18, bold=True, color=AMBER)
bullets(
    s,
    0.85,
    2.1,
    5.5,
    3.9,
    [
        "The fine-tuned phase model (mIoU 0.354 vs 0.274) gains only on labels made by a rule, not on labels a person made",
        "Cloud-VM and Kubernetes deployments are written and validated, never run on real infrastructure",
        "The clean retrieval ablation and the operator usability study are not done",
        "Cross-camera linking uses time and the camera map; it never recognises people",
        "Stored footage expires after 24 h, so a demo needs a fresh replay",
    ],
    size=13.5,
    after=8,
)
s.card(6.73, 1.5, 6.0, 3.95, TEAL_F, line=TEAL, lw=1.5)
s.text(6.98, 1.58, 5.5, 0.45, "Next steps", size=18, bold=True, color=TEAL)
bullets(
    s,
    6.98,
    2.1,
    5.5,
    3.9,
    [
        "Label more incidents by hand; retrain and test on those only",
        "Run the stack on a real VM and exercise the hybrid and cloud profiles",
        "Run the usability study with real operators",
        "Close correlation groups later, so late-judged events still link across cameras",
        "Index daily reports into the assistant's knowledge",
    ],
    size=13.5,
    after=8,
)
s.rect(0.6, 5.7, 12.13, 1.2, fill=CARD2, line=LINE, r=0.1)
s.text(0.6, 5.7, 12.13, 1.2, [{"text": "Thank you  ·  Questions?", "size": 28, "bold": True, "align": "c", "after": 4}, {"text": "The demo video, the study guide and the source are in the repository", "size": 13, "color": MUTED, "align": "c"}], anchor="m")


# ---- build -----------------------------------------------------------------------------------------
if __name__ == "__main__":
    out = HERE / "GenAI-VMS-overview.pptx"
    deck.save_pptx(out, HERE / ".build")
    print(f"wrote {out} ({len(deck.slides)} slides)")
    if len(sys.argv) > 1:
        pv = Path(sys.argv[1])
        pv.mkdir(parents=True, exist_ok=True)
        warns: list[str] = []
        for i in range(len(deck.slides)):
            warns += deck.preview(i, pv / f"slide-{i + 1:02d}.png")
        print("\n".join(warns) if warns else "no text overflows")
