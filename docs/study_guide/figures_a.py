"""Diagrams for parts 1-3: the problem, the big picture, and one clip's journey."""

from __future__ import annotations

from svg import Canvas, chain


def problem() -> str:
    c = Canvas(760, 250)
    c.group(10, 10, 360, 230, "TODAY: a wall of screens and a person", "bad")
    for i in range(3):
        for j in range(3):
            c.box(30 + i * 62, 40 + j * 44, 54, 36, "cam", "plain", size=9)
    c.box(235, 85, 110, 70, "One tired\nperson\nwatching", "bad", size=12)
    c.text(190, 205, '"Find the man in the red jacket from\nyesterday evening" = scrub hours of video', size=10, italic=True)
    c.arrow(385, 125, 420, 125, "", dashed=False)
    c.group(430, 10, 320, 230, "WITH THIS PROJECT", "ai")
    c.box(450, 45, 130, 44, "Understands\nevery clip", "ai", size=11)
    c.box(600, 45, 130, 44, "Searches in\nplain words", "ai", size=11)
    c.box(450, 105, 130, 44, "Raises + checks\nalerts itself", "event", size=11)
    c.box(600, 105, 130, 44, "Writes the\nincident report", "ui", size=11)
    c.text(590, 195, '"Show me a person in a red top near the\nservice door" answered in under a second', size=10, italic=True)
    return c.render()


def big_picture() -> str:
    c = Canvas(780, 560)
    # media row
    c.group(10, 10, 760, 100, "1. GETTING THE VIDEO IN", "media", right=True)
    c.box(30, 42, 110, 50, "Cameras\n(or simulator)", "media", size=11)
    c.box(190, 42, 130, 50, "MediaMTX\nlive re-broadcast", "media", size=11)
    c.box(370, 42, 140, 50, "Ingestion\ncuts 10 s pieces", "media", size=11)
    c.cylinder(580, 38, 170, 58, "MinIO (video + pictures)", "store", size=10)
    c.arrow(140, 67, 190, 67)
    c.arrow(320, 67, 370, 67)
    c.arrow(510, 67, 580, 67)
    # perception row
    c.group(10, 125, 760, 100, "2. UNDERSTANDING WHAT IS IN IT", "ai", right=True)
    c.box(30, 157, 150, 50, "Perception\nYOLO + tracker + SigLIP", "ai", size=11)
    c.box(230, 157, 150, 50, '"Digital twin"\nJSON per 10 s piece', "ai", size=11)
    c.box(430, 157, 150, 50, "Indexer\nfiles it for search", "ai", size=11)
    c.cylinder(620, 152, 65, 60, "Postgres", "store", size=9)
    c.cylinder(695, 152, 65, 60, "Qdrant", "store", size=9)
    c.arrow(180, 182, 230, 182)
    c.arrow(380, 182, 430, 182)
    c.arrow(580, 182, 620, 182)
    c.poly_arrow([(445, 92), (445, 118), (105, 118), (105, 157)], "")
    # events row
    c.group(10, 240, 760, 100, "3. NOTICING AND CHECKING THINGS", "event", right=True)
    c.box(30, 272, 150, 50, "Events service\n6 rules", "event", size=11)
    c.box(230, 272, 150, 50, "VLM gate\n\"is it real?\"", "ai", size=11)
    c.box(430, 272, 150, 50, "Correlation\nlinks cameras", "event", size=11)
    c.box(620, 272, 140, 50, "Alerts\nopen / ack / resolved", "event", size=11)
    c.arrow(180, 297, 230, 297)
    c.arrow(380, 297, 430, 297)
    c.arrow(580, 297, 620, 297)
    c.poly_arrow([(305, 207), (305, 240), (105, 240), (105, 272)], "")
    # genai row
    c.group(10, 355, 760, 110, "4. EXPLAINING AND ANSWERING (the GenAI part)", "ai", right=True)
    c.box(30, 390, 140, 56, "Search\nfast / reason / JIT", "ai", size=11)
    c.box(190, 390, 140, 56, "Reasoning\nphases + report", "ai", size=11)
    c.box(350, 390, 140, 56, "Assistant\nask in chat", "ai", size=11)
    c.box(510, 390, 120, 56, "Daily\nreport", "ai", size=11)
    c.box(650, 390, 110, 56, "Timeline\n+ cases", "ai", size=11)
    c.cylinder(250, 478, 280, 38, "LLM gateway  ->  Ollama (local)  |  Gemini / Groq (cloud)", "ai", size=10)
    # UI
    c.box(30, 520, 720, 34, "API (login, roles, live push)   ->   React dashboard in the browser", "ui", size=12, bold=True)
    return c.render()


def analogy() -> str:
    c = Canvas(780, 420)
    rows = [
        ("Camera + MediaMTX", "CCTV camera + the building's cable room", "media"),
        ("Ingestion", "A mail clerk who cuts a long tape into 10-second envelopes", "media"),
        ("MinIO (object storage)", "The warehouse: huge boxes (video) on shelves with addresses", "store"),
        ("Kafka", "The post office: small notes with addresses, never the heavy parcels", "media"),
        ("Perception", "A detective who writes a report card for every envelope", "ai"),
        ("Digital twin", "The report card: who/what is in the scene, where, doing what", "ai"),
        ("Postgres", "The filing cabinet: exact facts, searchable by column", "store"),
        ("Qdrant", "A map of meaning: similar things sit close together", "store"),
        ("Events + VLM gate", "A smoke alarm + a human glance that says 'real fire or toast?'", "event"),
        ("Correlation", "Connecting dots: the same suspicious thing seen by two cameras", "event"),
        ("LLM gateway + GPU lease", "A switchboard operator + ONE chair for the GPU: one model sits at a time", "ai"),
        ("Reasoning / report", "A junior analyst writing the incident report with footnotes", "ai"),
    ]
    c.text(150, 16, "Part of the system", size=12, bold=True)
    c.text(550, 16, "Everyday picture", size=12, bold=True)
    y = 34
    for name, pic, kind in rows:
        c.box(10, y, 260, 28, name, kind, size=11, bold=True)
        c.box(285, y, 485, 28, pic, "plain", size=11)
        y += 32
    return c.render()


def clip_journey() -> str:
    c = Canvas(780, 640)
    steps = [
        ("1", "Camera cam03 sends video.\nMediaMTX re-broadcasts it (live view works from here).", "media"),
        ("2", "Ingestion cuts it into 10 s files, saves them in MinIO,\ntakes 1 picture per second, and posts a note on Kafka.", "media"),
        ("3", "Perception reads the note, loads the pictures, finds people/cars/bags,\nfollows each with an ID (cam03-t412), builds the digital twin.", "ai"),
        ("4", "Indexer files the twin: facts into Postgres,\n'meaning vectors' into Qdrant (so search can find it).", "store"),
        ("5", "Events service tests 6 rules on the twin.\nA person stayed 60 s in a zone? -> 'loitering' candidate.", "event"),
        ("6", "VLM gate: a vision model LOOKS at the pictures and answers\nyes / no / unsure + a caption. 'no' = thrown away. 'yes' = verified event.", "ai"),
        ("7", "API turns it into an alert and pushes it to the dashboard live.\nCorrelation links it with events on neighbouring cameras.", "event"),
        ("8", "Reasoning (automatic for severe ones, or when you click Analyze):\nfind the 5 phases, read each camera, write the report with citations.", "ai"),
        ("9", "Everything is now searchable, askable, listed on the timeline,\nand summarised in tomorrow's daily report.", "ui"),
    ]
    y = 10
    for i, (n, text, kind) in enumerate(steps):
        c.circle(34, y + 28, 18, n, kind, size=14)
        c.box(66, y, 700, 56, text, kind, size=11)
        if i < len(steps) - 1:
            c.arrow(34, y + 48, 34, y + 66)
        y += 70
    return c.render()


def ingestion() -> str:
    c = Canvas(780, 250)
    c.box(10, 90, 110, 60, "Camera\nstream (RTSP)", "media", size=11)
    c.box(160, 90, 120, 60, "ffmpeg\n(no re-encode)", "media", size=11)
    c.arrow(120, 120, 160, 120)
    # tape cut into segments
    for i in range(5):
        c.box(320 + i * 58, 40, 52, 36, f"seg {i + 1}", "media", size=10)
    c.text(465, 25, "10-second segments (.ts files)", size=11, bold=True)
    c.arrow(280, 112, 320, 70)
    c.cylinder(330, 150, 150, 55, "MinIO: vms-segments", "store", size=10)
    c.cylinder(500, 150, 150, 55, "MinIO: vms-keyframes", "store", size=10)
    c.arrow(400, 78, 400, 150, "saves")
    c.arrow(560, 78, 560, 150, "1 picture / second")
    c.box(640, 40, 125, 56, "Kafka note\nsegment.v1\n(URI, times)", "event", size=10)
    c.arrow(630, 60, 640, 60)
    c.text(390, 235, "If the stream drops: wait 1, 2, 4... up to 30 s and reconnect; the next note says gap_before = true.", size=10, italic=True)
    return c.render()


def twin() -> str:
    c = Canvas(780, 330)
    c.box(10, 20, 120, 60, "10 s segment\n(video)", "media", size=11)
    c.arrow(130, 50, 170, 50)
    c.box(170, 20, 120, 60, "Sample frames\n2-5 per second", "ai", size=11)
    c.arrow(290, 50, 330, 50)
    c.box(330, 10, 130, 36, "YOLO11: what\nand where?", "ai", size=10)
    c.box(330, 54, 130, 36, "ByteTrack: same\nobject over time", "ai", size=10)
    c.box(330, 98, 130, 36, "Attributes: colour,\nzone, speed", "ai", size=10)
    c.box(330, 142, 130, 36, "SigLIP 2: a 'meaning\nvector' per object", "ai", size=10)
    c.arrow(460, 90, 500, 90)
    # json card
    c.box(500, 10, 270, 300, "", "store")
    c.text(635, 28, "THE DIGITAL TWIN (JSON)", size=11, bold=True)
    lines = [
        '"segment_id": "cam03_..._000123"',
        '"frames": [ {',
        '   "ts": "10:15:02.5",',
        '   "objects": [ {',
        '      "track_id": "cam03-t412",',
        '      "category": "person",',
        '      "bbox": [0.31, 0.22, 0.52, 0.81],',
        '      "attributes": {"upper_color":"red"},',
        '      "zones": ["staff-doorway"],',
        '      "motion": {"speed": 0.02}',
        "   } ] } ],",
        '"tracks": [ {"track_id":"cam03-t412",',
        '    "dwell_s": 47.0, "best_crop": "s3://..."} ]',
    ]
    for i, line in enumerate(lines):
        c.text(515, 52 + i * 19, line, size=9, anchor="start")
    c.text(240, 260, 'Why "twin"? It is a small, structured copy of what the\nvideo CONTAINS, so search, rules and reports read this\nand never have to re-watch the video.', size=11, italic=True)
    c.text(240, 310, "Stays small (a few KB) -> fits on Kafka as a link; the full JSON lives in MinIO.", size=10, italic=True)
    return c.render()


def kafka() -> str:
    c = Canvas(780, 330)
    c.text(390, 16, "Kafka = the post office. Services drop small notes; others pick up what they care about.", size=12, bold=True)
    prod = [("ingestion", "media"), ("perception", "ai"), ("events", "event"), ("correlation", "event"), ("reasoning", "ai")]
    topics = ["vms.segments.v1", "vms.twin.v1", "vms.events.v1", "vms.correlations.v1", "vms.incidents.v1"]
    cons = ["perception", "indexer + events", "correlation + indexer + api", "reasoning + api", "indexer + api"]
    for i, ((p, k), t, co) in enumerate(zip(prod, topics, cons)):
        y = 40 + i * 56
        c.box(10, y, 120, 40, p, k, size=11)
        c.arrow(130, y + 20, 200, y + 20, "writes")
        c.box(200, y, 190, 40, t, "plain", size=11, bold=True)
        c.arrow(390, y + 20, 460, y + 20, "read by")
        c.box(460, y, 310, 40, co, "plain", size=11)
    c.text(390, 322, "Failures: a note that keeps failing goes to  vms.dlq.v1  (dead-letter box) instead of blocking the line.", size=10, italic=True)
    return c.render()


def stores() -> str:
    c = Canvas(780, 400)
    cols = [
        (10, 170, "MinIO\n(object storage)", "Big files:", "video segments\nkeyframe pictures\nobject crops\ntwin JSON\nevidence frames\nPDF reports\nmask files\nmodel adapters", 8),
        (200, 170, "PostgreSQL\n(exact facts)", "Tables by area:", "core: users, cameras, zones,\nalerts, cases\nmedia: segments\nvision: tracks\nevents: events, groups\nreasoning: jobs, incidents,\ndaily reports\nretrieval: search logs", 8),
        (390, 170, "Qdrant\n(meaning vectors)", "Collections:", "frames (one per keyframe)\ntracks (one per object)\nknowledge (event captions,\nreport sections: search by\nmeaning AND by words)", 5),
        (580, 190, "Redis\n(quick coordination)", "Short-lived things:", "GPU lease (the one chair)\nresponse cache\nlive-push channel\ntracker checkpoint\nrate-limit counters", 5),
    ]
    for x, w, title, head, body, n in cols:
        c.cylinder(x, 20, w, 100, title, "store", size=12)
        c.text(x + w / 2, 142, head, size=11, bold=True)
        c.text(x + w / 2, 160 + n * 6.5 + 6, body, size=10)
    c.box(10, 300, 760, 80, "", "warn")
    c.text(390, 318, "Rule of thumb for presenting", size=11, bold=True)
    c.text(390, 352, "MinIO = the heavy stuff.  Postgres = what happened, exactly.  Qdrant = what it LOOKS like / MEANS.  Redis = traffic lights.\nKafka only carries the small notes that point at these.", size=10)
    return c.render()


def events() -> str:
    c = Canvas(780, 380)
    c.box(10, 30, 140, 56, "Digital twin\n(every 10 s)", "ai", size=11)
    c.arrow(150, 58, 190, 58)
    c.box(190, 20, 190, 76, "6 RULES\nintrusion.restricted/after_hours\nloitering | crowding\nabandoned_object | running", "event", size=10)
    c.arrow(380, 58, 420, 58, "hit")
    c.box(420, 30, 130, 56, "CANDIDATE\n(a suspicion)", "event", size=11)
    c.arrow(550, 58, 590, 58)
    c.box(590, 15, 180, 86, "VLM GATE\nqwen2.5-VL looks at up\nto 4 keyframes and\nanswers with a caption", "ai", size=10)
    c.arrow(680, 101, 680, 150, "")
    c.box(570, 150, 90, 50, "NO\nrejected\n(kept, silent)", "bad", size=9)
    c.box(670, 150, 100, 50, "YES\nverified event\n-> published", "ai", size=9)
    c.text(120, 135, "Cheap first, expensive second:", size=11, bold=True)
    c.text(120, 168, "rules cost almost nothing, so they run on\neverything; the vision model is slow and\nuses the GPU, so it only looks at the\nfew suspicions the rules raised.", size=10)
    c.group(10, 235, 760, 130, "What happens when the AI model is down? (design rule: degrade, don't die)", "warn")
    c.box(30, 262, 220, 80, "Low-severity rule:\nevent is still stored,\nflagged 'unverified'", "plain", size=10)
    c.box(280, 262, 220, 80, "Medium+ severity:\ncandidate WAITS and is\nretried with back-off", "plain", size=10)
    c.box(530, 262, 220, 80, "Recording + playback\nnever depend on any of\nthis. They keep working.", "ui", size=10)
    return c.render()


def alert_states() -> str:
    c = Canvas(780, 140)
    c.box(30, 40, 130, 56, "OPEN\n(new alert)", "event", size=12)
    c.box(330, 40, 150, 56, "ACKNOWLEDGED\n(someone is on it)", "event", size=11)
    c.box(650, 40, 120, 56, "RESOLVED\n(done / false alarm)", "ai", size=11)
    c.arrow(160, 68, 330, 68, "operator clicks Acknowledge")
    c.arrow(480, 68, 650, 68, "operator clicks Resolve")
    c.poly_arrow([(95, 40), (95, 22), (710, 22), (710, 40)], "")
    c.text(400, 10, "can resolve straight from OPEN (false alarm)", size=10, italic=True)
    c.text(390, 125, "Two operators click at once? The database lets exactly one win; the other gets a clear 409 message.", size=10, italic=True)
    return c.render()


def correlation() -> str:
    c = Canvas(780, 400)
    c.group(10, 10, 370, 230, "CAMERA MAP (topology)", "plain")
    c.box(30, 50, 90, 40, "cam01\nGate", "media", size=10)
    c.box(150, 50, 90, 40, "cam02\nYard", "media", size=10)
    c.box(270, 50, 90, 40, "cam03\nCorridor", "media", size=10)
    c.arrow(120, 70, 150, 70, "")
    c.arrow(150, 75, 120, 75, "")
    c.arrow(240, 70, 270, 70, "")
    c.text(135, 105, "transit:\n5-90 s", size=9)
    c.text(255, 105, "overlap:\nsame area", size=9)
    c.text(195, 175, "Two kinds of link:\n  overlap = two views of one area\n  transit = walking from A to B takes\n  between min and max seconds", size=10)
    c.group(400, 10, 370, 230, "SAME STORY, ON A CLOCK", "event")
    c.text(410, 40, "time ->", size=10, anchor="start")
    c.box(420, 55, 90, 28, "cam01 event", "event", size=10)
    c.box(520, 95, 90, 28, "cam02 event", "event", size=10)
    c.box(640, 135, 90, 28, "cam03 event", "event", size=10)
    c.text(585, 200, "close in time AND the cameras are linked\n=> same group (a 'correlation group')", size=10, bold=True)
    c.group(10, 255, 760, 135, "HOW GROUPS ARE BUILT  (analogy: friends of friends)", "ai")
    c.text(390, 300, "If A knows B and B knows C, then A, B and C are one friend group. Events work the same way:\nlink = 'compatible type' x 'edge exists' x 'times fit'.  Union-find merges chains of links into one group.", size=11)
    c.text(390, 350, "Group stays OPEN while new linked events arrive, CLOSES after a quiet period -> announced -> Reasoning may analyse it.\nTwo groups that turn out to be one are MERGED (oldest survives); every event is in at most one live group.", size=10, italic=True)
    return c.render()


def consumer_flow() -> str:
    c = Canvas(780, 210)
    items = [("1. A note arrives\nfrom Kafka", "media"), ("2. VALIDATE\nright shape and\nversion?", "event"), ("3. WRITE\nidempotently\n(safe to repeat)", "store"), ("4. COMMIT\n'I have handled\nthis one'", "ai")]
    x = 10
    boxes = []
    for t, k in items:
        boxes.append(c.box(x, 30, 160, 70, t, k, size=11))
        x += 200
    for i in range(3):
        c.arrow(boxes[i][0] + 160, 65, boxes[i + 1][0], 65)
    c.box(210, 140, 160, 56, "Invalid or keeps failing:\nretry, then dead-letter box", "bad", size=10)
    c.poly_arrow([(290, 100), (290, 140)], "")
    c.text(560, 168, "Crash between 3 and 4?\nThe note is delivered again, step 3 does\nnothing new, and nothing is duplicated.", size=10, italic=True)
    return c.render()
