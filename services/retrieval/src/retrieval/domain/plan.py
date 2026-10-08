"""Query understanding that needs no model: vocabulary, relative times, the fallback plan.

A 3B model decomposes a query well enough for visual phrasings and sub-questions, but it is
unreliable at dates and at keeping to the detector's vocabulary, so these functions are the
authority on both: whatever the model said, categories are mapped onto what perception can
emit, and a time expression in the text beats a time the model computed.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from vms_common.contracts.search import (
    QueryEntity,
    QueryPlan,
    QuerySpatial,
    QueryTemporal,
)

# detector category -> words that mean it. Order matters only for readability.
CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "person": (
        "person",
        "people",
        "man",
        "men",
        "woman",
        "women",
        "pedestrian",
        "someone",
        "somebody",
        "individual",
        "guy",
        "visitor",
        "student",
        "crowd",
        "walker",
        "human",
    ),  # fmt: skip
    "backpack": ("backpack", "rucksack", "bag"),
    "handbag": ("handbag", "purse", "bag"),
    "suitcase": ("suitcase", "luggage", "trolley"),
    "car": ("car", "cars", "sedan", "suv", "vehicle", "vehicles", "taxi"),
    "bicycle": ("bicycle", "bike", "cycle", "cyclist"),
    "motorcycle": ("motorcycle", "motorbike", "scooter"),
    "bus": ("bus",),
    "truck": ("truck", "lorry"),
}

COLOR_WORDS: dict[str, str] = {
    "gray": "gray", "grey": "gray", "silver": "gray",
    "blue": "blue", "navy": "blue",
    "orange": "orange", "black": "black", "dark": "black",
    "green": "green", "red": "red", "cyan": "cyan", "purple": "purple",
    "yellow": "yellow", "pink": "pink", "white": "white",
}  # fmt: skip

# event type hints from action words
# Whole words (a plural "s"/"es" is allowed): "ran" must not be found inside "entrance" or "orange".
EVENT_HINTS: dict[str, tuple[str, ...]] = {
    "intrusion": (
        "intrusion", "intruder", "trespass", "trespassing", "trespasser", "restricted", "enter",
        "entered", "entering", "breach", "breached",
    ),
    "loitering": ("loiter", "loitering", "lingering", "waiting", "standing around", "stationary"),
    "crowding": ("crowd", "crowding", "crowded", "gathering", "gathered", "many people", "group"),
    "running": ("run", "running", "ran", "runner", "rushing", "sprinting", "chasing"),
    "abandoned_object": ("abandoned", "unattended", "left behind", "left a bag", "left bag"),
}  # fmt: skip
_HINT_RE = {
    t: re.compile("|".join(rf"(?<![a-z]){re.escape(k)}(?:e?s)?(?![a-z])" for k in kws))
    for t, kws in EVENT_HINTS.items()
}

_WORD = re.compile(r"[a-z]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _forms(word: str) -> set[str]:
    """The word and what it would be in the singular ("buses" -> "bus", "lorries" -> "lorry")."""
    out = {word}
    if word.endswith("ies") and len(word) > 4:
        out.add(word[:-3] + "y")
    if word.endswith("es") and len(word) > 3:
        out.add(word[:-2])
    if word.endswith("s") and len(word) > 2:
        out.add(word[:-1])
    return out


def categories_in(text: str) -> list[str]:
    words = {f for w in _words(text) for f in _forms(w)}
    return [cat for cat, syn in CATEGORY_WORDS.items() if words.intersection(syn)]


_NOT_A_COLOUR_AFTER_DARK = frozenset({"hours", "night", "outside", "conditions", "time"})


def colors_in(text: str) -> list[str]:
    """Colour words in `text`. "dark" means black clothing ("a dark jacket") but not the time of
    day ("after dark", "in the dark"): it counts only when a describing word follows it."""
    seen: list[str] = []
    words = _words(text)
    for i, w in enumerate(words):
        c = COLOR_WORDS.get(w)
        if w == "dark":
            following = words[i + 1] if i + 1 < len(words) else None
            if following is None or following in _NOT_A_COLOUR_AFTER_DARK:
                continue
        if c and c not in seen:
            seen.append(c)
    return seen


def zones_in(text: str, known_zones: list[str]) -> list[str]:
    """Areas the text names, as whole words ("gate" is not in "investigate")."""
    low = text.lower().replace("-", " ")
    return [
        z
        for z in known_zones
        if re.search(rf"(?<![a-z0-9]){re.escape(z.lower().replace('-', ' '))}(?![a-z0-9])", low)
    ]


def event_hints_in(text: str) -> list[str]:
    low = text.lower()
    return [t for t, rx in _HINT_RE.items() if rx.search(low)]


_AGO = re.compile(r"\b(?:last|past)\s+(\d+)\s*(second|sec|minute|min|hour|hr|day)s?\b")
_AGO_BARE = re.compile(r"\b(?:last|past)\s+(hour|minute|day)\b")
_UNIT = {
    "second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400
}  # fmt: skip


_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
    "dec": 12,
}  # fmt: skip
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\b(?:,?\s+(\d{{4}}))?"
)
_MONTH_DAY = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?")


def find_date(text: str, today: date) -> date | None:
    """A calendar date written in `text` (2026-10-04, 4 October, October 4th, the 4th of October),
    or None. Without a year it is the most recent such date that is not after `today`."""
    low = text.lower()
    m = _ISO_DATE.search(low)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        explicit_year = True
    else:
        m = _DAY_MONTH.search(low)
        if m:
            day, month, year_s = int(m.group(1)), _MONTHS[m.group(2)], m.group(3)
        else:
            m = _MONTH_DAY.search(low)
            if not m:
                return None
            month, day, year_s = _MONTHS[m.group(1)], int(m.group(2)), m.group(3)
        year, explicit_year = (int(year_s), True) if year_s else (today.year, False)
    try:
        found = date(year, month, day)
    except ValueError:
        return None
    if not explicit_year and found > today:
        try:
            found = date(year - 1, month, day)
        except ValueError:
            return None
    return found


def resolve_time(query: str, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    """The window a time expression in `query` means, in UTC, or None if there is none."""
    low = query.lower()
    local = now.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)

    day = find_date(low, local.date())
    if day is not None:  # a named day: the whole of it, on the site's clock
        start = datetime(day.year, day.month, day.day, tzinfo=tz)
        return start.astimezone(now.tzinfo), (start + timedelta(days=1)).astimezone(now.tzinfo)

    m = _AGO.search(low)
    if m:
        return now - timedelta(seconds=int(m.group(1)) * _UNIT[m.group(2)]), now
    m = _AGO_BARE.search(low)
    if m:
        return now - timedelta(seconds=_UNIT[m.group(1)]), now
    if "yesterday" in low:
        return (midnight - timedelta(days=1)).astimezone(now.tzinfo), midnight.astimezone(
            now.tzinfo
        )
    if "last night" in low:
        return (midnight - timedelta(hours=6)).astimezone(now.tzinfo), (
            midnight + timedelta(hours=6)
        ).astimezone(now.tzinfo)
    parts = {"this morning": (0, 12), "this afternoon": (12, 18), "this evening": (17, 24),
             "tonight": (18, 24)}  # fmt: skip
    for phrase, (h0, h1) in parts.items():
        if phrase in low:
            return (
                (midnight + timedelta(hours=h0)).astimezone(now.tzinfo),
                min((midnight + timedelta(hours=h1)).astimezone(now.tzinfo), now),
            )
    if "today" in low:
        return midnight.astimezone(now.tzinfo), now
    return None


def heuristic_plan(
    query: str, *, now: datetime, tz: ZoneInfo, known_zones: list[str] | None = None
) -> QueryPlan:
    """A plan built from vocabulary alone. Used when no model answered, and to complete one
    that did."""
    colors = colors_in(query)
    cats = categories_in(query) or []
    entities = [
        QueryEntity(
            id=f"e{i + 1}",
            category=c,
            attributes={"color": colors[0]} if colors and i == 0 else {},
        )
        for i, c in enumerate(cats[:3])
    ]
    window = resolve_time(query, now, tz)
    return QueryPlan(
        original=query,
        entities=entities,
        actions=[],
        spatial=QuerySpatial(zones=zones_in(query, known_zones or [])),
        temporal=QueryTemporal(start=window[0], end=window[1]) if window else QueryTemporal(),
        visual_queries=[query.strip()],
        text_queries=[query.strip()],
        event_types_hint=event_hints_in(query),
        source="heuristic",
    )


def finalize_plan(
    plan: QueryPlan, *, now: datetime, tz: ZoneInfo, known_zones: list[str]
) -> QueryPlan:
    """Make a model's plan safe to filter with: detector categories only, zones that exist,
    times from the text when the text has any (else the model's, clamped to the past)."""
    query = plan.original
    detector = set(CATEGORY_WORDS)

    entities: list[QueryEntity] = []
    for e in plan.entities:
        cat = e.category.lower().strip()
        mapped = cat if cat in detector else next(iter(categories_in(cat)), None)
        if mapped:
            colors = colors_in(" ".join(e.attributes.values()))
            attrs = {"color": colors[0]} if colors else {}
            entities.append(QueryEntity(id=e.id, category=mapped, attributes=attrs))
    for cat in categories_in(query):
        if not any(e.category == cat for e in entities):
            entities.append(QueryEntity(id=f"e{len(entities) + 1}", category=cat))
    # A colour named in the text but dropped by the model still belongs on the first entity.
    text_colors = colors_in(query)
    if text_colors and entities and not any("color" in e.attributes for e in entities):
        entities[0] = entities[0].model_copy(update={"attributes": {"color": text_colors[0]}})

    # An area the text names is the area. Only when it names none is the model's choice used (it may
    # read "by the door" as the service door), and a small model answers "which areas?" by listing
    # every area it was shown (recorded: four of five on a query naming one), so more than two
    # is no choice at all.
    zones = zones_in(query, known_zones)
    if not zones:
        chosen = [z for z in plan.spatial.zones if z in known_zones]
        zones = chosen if len(chosen) <= 2 else []
    from_text = resolve_time(query, now, tz)
    if from_text:
        temporal = QueryTemporal(start=from_text[0], end=from_text[1])
    else:
        start, end = plan.temporal.start, plan.temporal.end
        if end and end > now:
            end = now
        if start and end and start >= end:
            start = end = None
        temporal = QueryTemporal(start=start, end=end)

    visual = [q.strip() for q in plan.visual_queries if q.strip()][:3] or [query.strip()]
    # Event types only from words the operator wrote: a small model volunteers hints the query
    # never implied, and a hint filters in verified events of that type.
    hints = event_hints_in(query)
    return plan.model_copy(
        update={
            "entities": entities,
            "spatial": QuerySpatial(zones=sorted(zones), cameras=plan.spatial.cameras),
            "temporal": temporal,
            "visual_queries": visual,
            "text_queries": [q.strip() for q in plan.text_queries if q.strip()][:3] or [query],
            "event_types_hint": hints,
        }
    )


def plan_categories(plan: QueryPlan) -> list[str]:
    """Detector categories the filter should accept: 'bag' means handbag *or* backpack."""
    cats: list[str] = []
    for e in plan.entities:
        cats.append(e.category)
        if e.category in ("backpack", "handbag") and _mentions_generic_bag(plan.original):
            cats.extend(["backpack", "handbag", "suitcase"])
    return list(dict.fromkeys(cats))


def _mentions_generic_bag(text: str) -> bool:
    words = set(_words(text))
    return "bag" in words or "bags" in words


def plan_colors(plan: QueryPlan) -> list[str]:
    return list(
        dict.fromkeys(e.attributes["color"] for e in plan.entities if "color" in e.attributes)
    )
