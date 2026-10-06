"""Query understanding that needs no model: vocabulary, relative times, the fallback plan.

A 3B model decomposes a query well enough for visual phrasings and sub-questions, but it is
unreliable at dates and at keeping to the detector's vocabulary, so these functions are the
authority on both: whatever the model said, categories are mapped onto what perception can
emit, and a time expression in the text beats a time the model computed.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
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
EVENT_HINTS: dict[str, tuple[str, ...]] = {
    "intrusion": ("intrusion", "intruder", "trespass", "restricted", "enter", "entered", "breach"),
    "loitering": ("loiter", "loitering", "lingering", "waiting", "standing around", "stationary"),
    "crowding": ("crowd", "crowding", "gathering", "gathered", "many people", "group"),
    "running": ("run", "running", "ran", "rushing", "sprinting", "chasing"),
    "abandoned_object": ("abandoned", "unattended", "left behind", "left a bag", "left bag"),
}

_WORD = re.compile(r"[a-z]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def categories_in(text: str) -> list[str]:
    words = set(_words(text))
    return [cat for cat, syn in CATEGORY_WORDS.items() if words.intersection(syn)]


def colors_in(text: str) -> list[str]:
    seen: list[str] = []
    for w in _words(text):
        c = COLOR_WORDS.get(w)
        if c and c not in seen:
            seen.append(c)
    return seen


def zones_in(text: str, known_zones: list[str]) -> list[str]:
    low = text.lower().replace("-", " ")
    return [z for z in known_zones if z.lower().replace("-", " ") in low]


def event_hints_in(text: str) -> list[str]:
    low = text.lower()
    return [t for t, kws in EVENT_HINTS.items() if any(k in low for k in kws)]


_AGO = re.compile(r"\b(?:last|past)\s+(\d+)\s*(second|sec|minute|min|hour|hr|day)s?\b")
_AGO_BARE = re.compile(r"\b(?:last|past)\s+(hour|minute|day)\b")
_UNIT = {
    "second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400
}  # fmt: skip


def resolve_time(query: str, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    """The window a time expression in `query` means, in UTC, or None if there is none."""
    low = query.lower()
    local = now.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)

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

    zones = [z for z in {*plan.spatial.zones, *zones_in(query, known_zones)} if z in known_zones]
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
