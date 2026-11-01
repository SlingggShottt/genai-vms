"""Diagrams for parts 4-7: the GenAI machinery, search, reasoning, assistant, UI, security, results."""

from __future__ import annotations

from svg import PALETTE, Canvas


def gateway() -> str:
    c = Canvas(780, 430)
    c.box(10, 20, 150, 50, "Any service\nasks for a TASK", "plain", size=11)
    c.text(85, 90, 'e.g. "event_verify",\n"phase_tg", "assistant"', size=9, italic=True)
    c.arrow(160, 45, 200, 45)
    c.box(200, 10, 190, 70, "REGISTRY\nconfig/models.yaml\ntask -> model, per profile", "ai", size=10)
    c.arrow(390, 45, 430, 45)
    c.box(430, 10, 150, 70, "PROFILE\nlocal | hybrid | cloud\n(one env variable)", "ai", size=10)
    c.arrow(580, 45, 620, 45)
    c.box(620, 10, 150, 70, "Try in order:\nmodel 1 -> fallback\n-> fallback", "ai", size=10)
    c.group(10, 110, 760, 130, "Every call goes through these steps (so no service ever talks to a model directly)", "plain")
    steps = ["cache hit?\n(Redis)", "wait for the\nGPU chair", "call the\nmodel", "validate the\nanswer shape", "retry once with\nthe errors quoted"]
    x = 25
    for s in steps:
        c.box(x, 145, 130, 56, s, "plain", size=10)
        x += 148
    for i in range(4):
        c.arrow(25 + i * 148 + 130, 173, 25 + (i + 1) * 148, 173)
    c.group(10, 255, 370, 165, "THE ONE CHAIR (GPU lease, in Redis)", "warn")
    c.box(30, 290, 90, 50, "Text model\nqwen2.5:3b", "ai", size=9)
    c.box(140, 290, 90, 50, "Vision model\nqwen2.5-VL", "ai", size=9)
    c.box(250, 290, 110, 50, "Fine-tuned\nadapter", "ai", size=9)
    c.text(195, 375, "The 4 GB GPU holds ONE model family at a time.\nWhoever holds the chair keeps it; others queue.\nIf the holder crashes, the chair frees itself\n(and after 15 min even if it is stuck).", size=9)
    c.group(400, 255, 370, 165, "WHY THIS MATTERS", "ai")
    c.text(585, 330, "- swap local <-> cloud with ONE setting, no code change\n- a model name is never written in code\n- every answer records WHICH model gave it (provenance)\n- structured JSON answers are validated, not trusted\n- prompts live in files with versions", size=10, anchor="middle")
    return c.render()


def search() -> str:
    c = Canvas(780, 480)
    c.box(10, 20, 120, 50, '"person in a red\ntop near the door"', "ui", size=10)
    c.arrow(130, 45, 170, 45)
    c.box(170, 20, 100, 50, "1. PLAN\nwhat/where/when", "ai", size=10)
    c.arrow(270, 45, 310, 45)
    c.box(310, 20, 100, 50, "2. ENCODE\ntext -> vector", "ai", size=10)
    c.arrow(410, 45, 450, 45)
    c.box(450, 5, 150, 80, "3. RETRIEVE\nframes + tracks (Qdrant)\nevent captions (Postgres)\nreports (knowledge)", "store", size=9)
    c.arrow(600, 45, 640, 45)
    c.box(640, 20, 130, 50, "4. FUSE\nRRF + 10 s windows", "ai", size=10)
    c.text(390, 105, "FAST MODE stops here  ->  results in ~0.25 s (visual similarity only)", size=11, bold=True, color="#16a34a")
    c.poly_arrow([(705, 70), (705, 125), (665, 125)], "")
    c.group(10, 135, 760, 130, "REASON MODE adds a language model that re-reads the best windows  (~15 s on this laptop)", "ai")
    c.box(30, 170, 210, 80, "DECOMPOSE (step 1)\nthe LLM turns the sentence into\n'person, red top, near door'\n+ sub-questions", "ai", size=9)
    c.box(285, 170, 220, 80, "RERANK (step 5)\nreads a text 'excerpt' of the twin for\nthe top 10 windows, 5 at a time:\nscore 0-1 + a short reason + what is\nUNKNOWN from the records", "ai", size=9)
    c.box(550, 170, 200, 80, "FINAL = 40% fused + 60% LLM score\n(weight is a setting)\ntrace shown on each result card", "ai", size=9)
    c.arrow(240, 210, 285, 210)
    c.arrow(505, 210, 550, 210)
    c.group(10, 280, 760, 110, "JIT (just in time) 'Look closer' - opt-in, slow on this laptop", "warn")
    c.box(30, 312, 230, 60, "The rerank said: 'cannot tell if\nthe bag is blue from the records'", "plain", size=9)
    c.box(290, 312, 230, 60, "A VISION model looks at that\nkeyframe and answers yes / no /\nunsure (cached; a 'yes' is remembered)", "ai", size=9)
    c.box(550, 312, 200, 60, "Answer goes back to the\nreranker -> rescored result", "ai", size=9)
    c.arrow(260, 342, 290, 342)
    c.arrow(520, 342, 550, 342)
    c.group(10, 400, 760, 70, "OTHER WAYS IN", "ui")
    c.text(390, 440, 'Search by IMAGE (upload a picture)   |   FIND SIMILAR (draw a box on a frame)   |   MASKS (outline the matched object, SAM)', size=11)
    return c.render()


def rrf() -> str:
    c = Canvas(780, 270)
    c.text(390, 14, "Reciprocal Rank Fusion (RRF): how two imperfect rankings become one better one", size=12, bold=True)
    c.text(110, 44, "Picture search says", size=11, bold=True)
    for i, w in enumerate(["window A", "window B", "window C", "window D"]):
        c.box(40, 56 + i * 36, 140, 28, f"{i + 1}.  {w}", "media", size=11)
    c.text(330, 44, "Caption/text search says", size=11, bold=True)
    for i, w in enumerate(["window C", "window A", "window E", "window B"]):
        c.box(260, 56 + i * 36, 140, 28, f"{i + 1}.  {w}", "event", size=11)
    c.text(220, 135, "+", size=22, bold=True)
    c.arrow(408, 130, 462, 130, "fuse")
    c.text(550, 44, "Score = sum of 1 / (60 + rank)", size=11, bold=True)
    rows = [("window A", "1/61 + 1/62 = 0.0325"), ("window C", "1/63 + 1/61 = 0.0323"), ("window B", "1/62 + 1/64 = 0.0318"), ("window D", "1/64 = 0.0156"), ("window E", "1/63 = 0.0159")]
    for i, (w, s) in enumerate(rows):
        c.box(470, 56 + i * 34, 295, 28, f"{w}   {s}", "ai", size=10)
    c.text(390, 245, "Something that BOTH searches like beats something only one likes. Hits within 10 s on one camera are merged into one 'window'.", size=10, italic=True)
    return c.render()


def phases() -> str:
    c = Canvas(780, 330)
    c.text(390, 14, "An incident is not one moment: it has five phases (borrowed from the MP-PVIR research paper)", size=12, bold=True)
    names = [("BASELINE", "normal scene,\nnothing unusual", "plain"), ("PRECURSOR", "first signs:\nlingering, watching", "warn"), ("ESCALATION", "it builds:\napproach, tension", "event"), ("ACTION", "the incident\nitself", "bad"), ("AFTERMATH", "what happens\nafter", "media")]
    x = 20
    for n, d, k in names:
        c.box(x, 34, 140, 66, n, k, size=12, bold=True, sub=d)
        x += 148
    c.text(60, 130, "time ->", size=10, anchor="start")
    c.text(390, 150, "The same incident seen by TWO cameras, each phase read separately:", size=11, bold=True)
    for r, cam in enumerate(["cam01 (gate)", "cam02 (yard)"]):
        y = 170 + r * 52
        c.text(55, y + 20, cam, size=10)
        x = 110
        for i, (n, d, k) in enumerate(names):
            c.box(x + i * 134, y, 128, 40, "caption + answers", k, size=9, sub="")
    c.box(20, 280, 740, 40, "Every sentence in the final report cites an evidence id like [ev-cap-03]. A claim that cites nothing is DROPPED, not invented.", "warn", size=10)
    return c.render()


def reasoning() -> str:
    c = Canvas(780, 520)
    steps = [
        ("TRIGGER", "A correlation group closes (severity high+)\nOR an operator clicks 'Analyze'.\nA job row is queued in Postgres.", "event"),
        ("GATHER", "Pick the primary camera, up to 2 cameras,\nwindow = event +/- 15 s. Load the keyframes\nfrom the twins in MinIO.", "media"),
        ("1. LOCATE PHASES (TG)", "Show 5 frames to the vision model: 'which phase\nis each frame?'  -> timeline of 5 stages.\nIf the model fails -> use the detector's own timing.", "ai"),
        ("2. READ EVIDENCE (PhaVR)", "For each phase x camera: show 2 frames + the event\ntype's questions (VQA bank). Get a caption and\nanswers. Frames are copied to a safe bucket.", "ai"),
        ("3. WRITE THE REPORT", "Two LLM calls: (a) stage summaries (b) causal chain,\nfactors, actions. Every claim must cite evidence ids;\nbad citations are quoted back and retried; uncited claims dropped.", "ai"),
        ("STORE + TELL", "Save report (Postgres) + PDF (MinIO), keep a JSON copy,\npublish incident.ready, push 'done' to browsers.\nProvenance records: which model, timings, fallbacks.", "store"),
    ]
    y = 6
    for i, (t, d, k) in enumerate(steps):
        c.box(10, y, 190, 76, t, k, size=11, bold=True)
        c.box(215, y, 555, 76, d, "plain", size=10)
        if i < len(steps) - 1:
            c.arrow(105, y + 76, 105, y + 86)
        y += 86
    return c.render()


def assistant() -> str:
    c = Canvas(780, 380)
    c.box(10, 40, 130, 56, '"How many\npeople were on\ncam01 today?"', "ui", size=10)
    c.arrow(140, 68, 180, 68)
    c.box(180, 20, 150, 96, "ROUTER / PLANNER\nclear question ->\nkeywords pick the tool\nelse the LLM picks\n(max 4 calls)", "ai", size=9)
    c.arrow(330, 68, 370, 68)
    c.group(370, 10, 400, 118, "7 TOOLS (fixed, parameterised SQL)", "store")
    tools = ["search_footage", "list_events", "list_incidents", "get_incident", "get_timeline", "count_objects", "get_daily_report"]
    for i, t in enumerate(tools):
        c.pill(385 + (i % 3) * 125, 38 + (i // 3) * 28, 118, t, "store", size=9)
    c.arrow(570, 128, 570, 160)
    c.box(370, 160, 400, 56, "Each tool returns TEXT with evidence tags\n[E:84912e49] event   [I:...] incident   [S:...] segment", "ai", size=10)
    c.arrow(570, 216, 570, 246)
    c.box(370, 246, 400, 56, "LLM writes the answer FROM that text only.\nThe server (not the model) turns tags into citation chips.", "ai", size=10)
    c.box(10, 250, 330, 120, "", "warn")
    c.text(175, 270, "Honesty rules built in", size=11, bold=True)
    c.text(175, 322, "- nothing found? it must say so, no guessing\n- a tag nobody handed out is reported, not cited\n- the first line is the tool's own sentence\n- answers stream live (SSE), last 12 messages kept", size=10)
    return c.render()


def frontend() -> str:
    c = Canvas(780, 330)
    pages = [
        ("Live wall", "all cameras live (WebRTC), status", "media"),
        ("Playback", "pick time range, HLS video, detection overlay, find similar here", "media"),
        ("Search", "fast / reason / look closer, by text or image", "ai"),
        ("Assistant", "chat with citations", "ai"),
        ("Events + alerts", "list, detail, keyframes, ack / resolve, Analyze", "event"),
        ("Incidents", "AI reports, phase band, PDF, similar incidents", "ai"),
        ("Timeline", "lanes per camera, correlation links, search in range", "event"),
        ("Cases", "save evidence into investigations with notes", "ui"),
        ("Reports", "daily security report + PDF", "ui"),
        ("Settings", "cameras, zones, camera links (admin)", "plain"),
    ]
    for i, (n, d, k) in enumerate(pages):
        col, row = i % 2, i // 2
        c.box(10 + col * 385, 8 + row * 62, 375, 54, n, k, size=12, bold=True, sub=d)
    return c.render()


def security() -> str:
    c = Canvas(780, 300)
    c.box(10, 30, 85, 50, "Browser\nlogs in", "ui", size=11)
    c.arrow(95, 55, 175, 55, "email +\npassword", dy=-20)
    c.box(175, 20, 140, 70, "API checks the\npassword (hashed),\nissues a JWT token\n(short-lived)", "plain", size=9)
    c.arrow(315, 55, 395, 55, "every call\ncarries it", dy=-20)
    c.box(395, 20, 140, 70, "API re-reads the user\nand ROLE from the DB\non every request", "plain", size=9)
    c.arrow(535, 55, 590, 55)
    c.box(590, 10, 180, 90, "403 if your role is\nnot allowed.\nRate limits: login 10/min,\nsearch 30, assistant 20", "event", size=9)
    roles = [
        ("VIEWER", "watch live + playback\nsearch, read events,\nincidents, reports, timeline", "media"),
        ("OPERATOR", "everything a viewer can\n+ see / acknowledge / resolve\nalerts, Analyze, cases, reports", "ai"),
        ("ADMIN", "everything\n+ manage users, cameras,\nzones, camera links", "event"),
    ]
    for i, (n, d, k) in enumerate(roles):
        c.box(10 + i * 258, 120, 248, 110, "", k)
        c.text(10 + i * 258 + 124, 140, n, size=12, bold=True)
        c.text(10 + i * 258 + 124, 188, d, size=10)
    c.text(390, 255, "Video links are presigned: temporary URLs that expire in 15 minutes and are made per request, never stored.", size=10, italic=True)
    c.text(390, 280, "No face recognition, no face blurring (out of scope by team decision). Every sensitive action is audit-logged.", size=10, italic=True)
    return c.render()


def deploy() -> str:
    c = Canvas(780, 380)
    c.group(10, 10, 370, 175, "ON ONE LAPTOP (what you demo)", "media")
    c.box(25, 40, 340, 56, "Docker Compose: Kafka, Postgres, Qdrant, MinIO, Redis,\nMediaMTX, ingestion, indexer, correlation, Grafana, Prometheus", "plain", size=9)
    c.box(25, 106, 340, 66, "On the host (need the GPU): Ollama, retrieval, reasoning,\napi, the React dev server  - started by deploy/demo/start.sh\nPerception + events gate run only when footage is refreshed", "ai", size=9)
    c.group(400, 10, 370, 175, "TWO LAPTOPS (the original plan)", "plain")
    c.box(415, 40, 160, 120, "Laptop A\nperception + indexer\n(detector on GPU)", "ai", size=10)
    c.box(595, 40, 160, 120, "Laptop B\nOllama, reasoning,\nretrieval, events gate", "ai", size=10)
    c.arrow(575, 100, 595, 100)
    c.arrow(595, 110, 575, 110)
    c.group(10, 200, 370, 170, "CLOUD VM (written, not deployed)", "warn")
    c.text(195, 285, "docker-compose.prod.yml + Caddy (HTTPS)\n'cloud' model profile (Gemini/Groq), no GPU\nrunbook + update.sh + GitHub Actions\nNEVER run on a real VM yet", size=10)
    c.group(400, 200, 370, 170, "KUBERNETES (manifests only)", "warn")
    c.text(585, 285, "deploy/k8s: kustomize base + overlays,\nGPU overlays, observability rules.\nValidated with kubeconform, tested render.\nNEVER applied to a real cluster yet", size=10)
    return c.render()


def lora() -> str:
    c = Canvas(780, 280)
    c.box(10, 30, 230, 130, "", "plain")
    c.text(125, 52, "BASE MODEL (3 billion numbers)", size=11, bold=True)
    c.text(125, 100, 'A very well-read student who\nknows a lot about everything\nbut has never seen OUR cameras.\nFrozen: we never change it.', size=10)
    c.arrow(240, 95, 290, 95, "+")
    c.box(290, 40, 190, 110, "", "ai")
    c.text(385, 62, "LoRA ADAPTER (~30 million)", size=11, bold=True)
    c.text(385, 108, 'A thin pack of sticky notes\nclipped onto the textbook:\n"in OUR task, answer like this".\nSmall, cheap to train, swappable.', size=10)
    c.arrow(480, 95, 530, 95, "=")
    c.box(530, 40, 235, 110, "FINE-TUNED BEHAVIOUR\n(same base, new habit)", "event", size=11, bold=True)
    c.box(10, 190, 755, 78, "", "warn")
    c.text(387, 206, "QLoRA = the base is also squeezed to 4 bits ('JPEG for model weights') so it fits in 4 GB of GPU memory.", size=10, bold=True)
    c.text(387, 240, "Our experiment: trained a 'phase locator' adapter on 138 camera-samples in ~50 minutes on the laptop GPU.\nIt always answers in the right shape, but did NOT clearly understand phases better than the untrained model (see chapter 7).", size=10)
    return c.render()


def bars(title: str, groups: list[str], series: list[tuple[str, list[float], str]], *, w: int = 760, h: int = 300, ymax: float = 1.0, ylabel: str = "") -> str:
    """Grouped bar chart with value labels."""
    c = Canvas(w, h)
    left, right, top, bottom = 55, 15, 36, 52
    plot_w, plot_h = w - left - right, h - top - bottom
    c.text(w / 2, 16, title, size=12, bold=True)
    for k in range(0, 6):
        v = ymax * k / 5
        y = top + plot_h - plot_h * k / 5
        c.raw(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        c.text(left - 6, y, f"{v:.2g}", size=9, anchor="end", color="#475569")
    gw = plot_w / len(groups)
    bw = min(46, (gw - 22) / len(series))
    for gi, g in enumerate(groups):
        gx = left + gi * gw + gw / 2
        c.text(gx, h - bottom + 16, g, size=10)
        for si, (name, vals, kind) in enumerate(series):
            v = vals[gi]
            bh = plot_h * v / ymax
            x = gx - len(series) * bw / 2 + si * bw
            fill, stroke = PALETTE[kind]
            c.raw(f'<rect x="{x:.1f}" y="{top + plot_h - bh:.1f}" width="{bw - 3:.1f}" height="{bh:.1f}" fill="{stroke}" opacity="0.85"/>')
            c.text(x + (bw - 3) / 2, top + plot_h - bh - 8, f"{v:.2f}", size=9)
    lx = left
    for name, _, kind in series:
        fill, stroke = PALETTE[kind]
        c.raw(f'<rect x="{lx}" y="{h - 18}" width="12" height="12" fill="{stroke}" opacity="0.85"/>')
        c.text(lx + 18, h - 12, name, size=10, anchor="start")
        lx += 20 + len(name) * 6.2 + 22
    if ylabel:
        c.text(12, top + plot_h / 2, ylabel, size=9)
    return c.render()


def adapter_chart() -> str:
    return bars(
        "Phase-location accuracy (mIoU, higher is better) by WHO MADE THE LABEL, 32 test samples",
        ["all samples (32)", "a person's labels (6)", "drafts that looked (17)", "padding-rule labels (8)"],
        [("untrained model", [0.274, 0.237, 0.278, 0.291], "plain"), ("fine-tuned adapter", [0.354, 0.196, 0.300, 0.556], "ai")],
        h=250,
    )


def retrieval_chart() -> str:
    return bars(
        "Does the right clip appear in the top k results? (36 queries, MEVA activity clips)",
        ["top 1", "top 5", "top 10"],
        [("random", [0.03, 0.13, 0.24], "plain"), ("fast mode", [0.14, 0.36, 0.56], "media"), ("reason mode", [0.22, 0.39, 0.67], "ai")],
        h=250,
    )


def latency_chart() -> str:
    c = Canvas(780, 185)
    c.text(390, 14, "Where the time goes in a search (seconds, median, measured on this laptop)", size=12, bold=True)
    rows = [
        ("FAST (total 0.22 s)", [("encode", 0.06, "media"), ("retrieve", 0.02, "store"), ("fuse", 0.14, "ai")], 0.22),
        ("REASON (total 15.5 s)", [("plan", 2.3, "media"), ("encode+retrieve+fuse", 0.4, "store"), ("LLM rerank", 12.8, "ai")], 15.5),
    ]
    scale = 560 / 15.5
    for r, (name, parts, tot) in enumerate(rows):
        y = 44 + r * 52
        c.text(10, y + 18, name, size=10, anchor="start", bold=True)
        x = 190
        for label, v, kind in parts:
            w = max(v * scale, 3)
            fill, stroke = PALETTE[kind]
            c.raw(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="34" fill="{fill}" stroke="{stroke}"/>')
            if w > 60:
                c.text(x + w / 2, y + 17, f"{label} {v}", size=9)
            x += w
    c.text(390, 135, "Fast mode is about 70x quicker. The extra time in reason mode is the 3B language model rereading candidates on a 4 GB GPU.", size=10, italic=True)
    c.text(390, 158, "Object masks: 1.3 s the first time (CPU), 9 ms when cached.   A vision-model call: ~3 s per image.   Event gate model load: ~8-14 s cold.", size=10, italic=True)
    return c.render()


def demo_flow() -> str:
    c = Canvas(780, 150)
    items = [("1 Live wall", "media"), ("2 Search\nfast vs reason", "ai"), ("3 Event ->\nAnalyze", "event"), ("4 Incident\nreport + PDF", "ai"), ("5 Ask the\nassistant", "ai"), ("6 Timeline\n+ case", "ui")]
    n = len(items)
    w = (760 - 25 * (n - 1)) / n
    for i, (t, k) in enumerate(items):
        x = 10 + i * (w + 25)
        c.box(x, 40, w, 66, t, k, size=11, bold=True)
        if i:
            c.arrow(x - 25 + 2, 73, x - 2, 73)
    c.text(390, 128, "The story arc: WATCH -> FIND -> UNDERSTAND -> EXPLAIN -> ASK -> INVESTIGATE", size=11, italic=True)
    return c.render()


def analyze_sequence() -> str:
    c = Canvas(780, 420)
    cols = [("Browser", 60, "ui"), ("API", 215, "plain"), ("Postgres", 370, "store"), ("Reasoning\nworker", 525, "ai"), ("LLM gateway\n+ Ollama", 690, "ai")]
    for name, x, k in cols:
        c.box(x - 50, 8, 100, 40, name, k, size=10, bold=True)
        c.raw(f'<line x1="{x}" y1="48" x2="{x}" y2="410" stroke="#94a3b8" stroke-dasharray="4 4"/>')
    X = {n.split("\n")[0]: x for n, x, _ in cols}
    steps = [
        ("Browser", "API", "1. click Analyze: POST /events/{id}/analyze", 75),
        ("API", "Postgres", "2. insert job (status: queued)", 105),
        ("API", "Browser", "3. 202 + job id (the UI starts watching)", 135),
        ("Reasoning", "Postgres", "4. claim the job (SKIP LOCKED)", 170),
        ("Reasoning", "LLM gateway", "5. phase task, evidence tasks, report tasks", 205),
        ("LLM gateway", "Reasoning", "answers (validated, with provenance)", 232),
        ("Reasoning", "Postgres", "6. progress: 'reading action - cam02' 0.45", 267),
        ("Reasoning", "API", "7. push job.progress via Redis", 297),
        ("API", "Browser", "WebSocket: browser updates its bar", 325),
        ("Reasoning", "Postgres", "8. store report + PDF, job = done", 360),
        ("API", "Browser", "9. push incident.ready; browser fetches the report", 392),
    ]
    for a, b, label, y in steps:
        x1, x2 = X[a], X[b]
        d = 6 if x2 > x1 else -6
        c.arrow(x1 + d, y, x2 - d, y, "", dashed=(a == "LLM gateway"))
        w = len(label) * 5.0 + 8
        c.raw(f'<rect x="{(x1 + x2) / 2 - w / 2:.1f}" y="{y - 19}" width="{w:.1f}" height="14" fill="white" fill-opacity="0.92"/>')
        c.text((x1 + x2) / 2, y - 9, label, size=9)
    return c.render()
