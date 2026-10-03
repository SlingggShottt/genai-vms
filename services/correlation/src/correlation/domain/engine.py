"""The correlation engine — pure functions over `Group`s (design_architecture.md §7.5).

    add_event       a verified event arrives: link it to the events of the site's open groups,
                    join/merge the groups it links (union-find), or start a group of its own.
    close_due       close the open groups nothing can still link to.
    due_for_publish which changed groups to announce now (open ones throttled).
    to_message      a group as a `correlation.v1` message.

Nothing here reads a clock or touches storage: callers pass `now`, and persist what the
functions return. Groups are mutated in place for speed; every group that changed is in the
returned list so the caller knows what to write.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from vms_common.contracts.correlation import CorrelationLink, CorrelationV1
from vms_common.ids import uuid7_str

from correlation.domain.config import CorrelationConfig
from correlation.domain.scoring import best_link
from correlation.domain.topology import Topology
from correlation.domain.types import EventRecord, Group, LinkRecord


def _age(group: Group) -> tuple[datetime, str]:
    return group.created_at, group.id


@dataclass
class AddOutcome:
    changed: list[Group] = field(default_factory=list)  # to upsert (survivor/new, then absorbed)
    new_links: list[LinkRecord] = field(default_factory=list)
    duplicate: bool = False
    group_id: str | None = None  # the group the event ended up in


def add_event(
    open_groups: Sequence[Group],
    event: EventRecord,
    *,
    topology: Topology,
    config: CorrelationConfig,
    now: datetime,
) -> AddOutcome:
    """Place `event`. `open_groups` is every open group (any site; others are ignored).

    A repeat of an event already in one of those groups is a no-op (`duplicate=True`): Kafka
    delivers at least once. (The caller also checks closed groups before calling.)
    """
    groups = [g for g in open_groups if g.status == "open" and g.site_id == event.site_id]
    for group in groups:
        if event.event_id in group.event_ids:
            return AddOutcome(duplicate=True, group_id=group.id)

    # 1. every link from the new event to an event of an open group
    links_by_group: dict[str, list[LinkRecord]] = {}
    for group in groups:
        for member in group.members:
            link = best_link(event, member, topology, config)
            if link is not None:
                links_by_group.setdefault(group.id, []).append(link)

    # 2. which of those groups can be joined without outgrowing the cap, oldest first so the
    #    oldest group survives a merge. (Not by id: UUIDv7 is only ordered across milliseconds,
    #    and a burst of events can create several groups within one; id breaks exact ties.)
    size = 1
    joined: list[Group] = []
    candidates = sorted((g for g in groups if g.id in links_by_group), key=_age)
    for group in candidates:
        if size + len(group.members) <= config.max_group_events:
            joined.append(group)
            size += len(group.members)

    if not joined:
        group = Group(id=uuid7_str(), site_id=event.site_id, created_at=now, members=[event])
        return AddOutcome(changed=[group], group_id=group.id)

    # 3. union: the oldest joined group absorbs the others and the event
    survivor, *absorbed = joined
    new_links = [link for g in joined for link in links_by_group[g.id]]
    for other in absorbed:
        survivor.members.extend(other.members)
        survivor.links.extend(other.links)
        other.links = []  # they live on the survivor now
        other.status = "merged"
        other.merged_into = survivor.id
        other.closed_at = now
        other.revision += 1
        other.publish_pending = True
    survivor.members.append(event)
    survivor.links.extend(new_links)
    survivor.revision += 1
    survivor.publish_pending = True
    return AddOutcome(changed=[survivor, *absorbed], new_links=new_links, group_id=survivor.id)


def close_due(
    open_groups: Iterable[Group], *, topology: Topology, config: CorrelationConfig, now: datetime
) -> list[Group]:
    """Close every open group whose last event ended longer ago than the longest time a
    neighbouring camera could still take to produce a linkable event, plus the grace period."""
    closed = []
    for group in open_groups:
        if group.status != "open":
            continue
        wait = topology.max_window_s(group.camera_ids) + config.grace_s
        if now - group.end_ts > timedelta(seconds=wait):
            group.status = "closed"
            group.closed_at = now
            group.revision += 1
            group.publish_pending = True
            closed.append(group)
    return closed


def _is_due(group: Group, config: CorrelationConfig, now: datetime) -> bool:
    if not group.publish_pending:
        return False
    if group.status != "open" or group.last_published_at is None:
        return True  # final states, and a group's first announcement, are never held back
    return now - group.last_published_at >= timedelta(seconds=config.publish_throttle_s)


def due_for_publish(
    groups: Iterable[Group], *, config: CorrelationConfig, now: datetime
) -> list[Group]:
    """Changed groups to announce now. A closed or merged group is final and goes out at once;
    an open one at most once per `publish_throttle_s` (it will be due again later: it stays
    pending until `mark_published` is called for it)."""
    return [group for group in groups if _is_due(group, config, now)]


def mark_published(group: Group, *, revision: int, now: datetime) -> None:
    """Record that `revision` of `group` went out. If the group changed meanwhile (a newer
    revision exists) it stays pending, so that newer state is still announced."""
    group.last_published_at = now
    if group.revision == revision:
        group.publish_pending = False


def to_message(group: Group) -> CorrelationV1:
    return CorrelationV1(
        group_id=group.id,
        site_id=group.site_id,
        status=group.status,
        revision=group.revision,
        event_ids=group.event_ids,
        camera_ids=group.camera_ids,
        event_types=group.event_types,
        start_ts=group.start_ts,
        end_ts=group.end_ts,
        max_severity=group.max_severity,  # type: ignore[arg-type]
        # A canonical order, so the message never depends on how the links were stored or loaded.
        links=[
            CorrelationLink(
                from_event=link.from_event,
                to_event=link.to_event,
                edge_type=link.edge_type,
                delta_s=link.delta_s,
                score=round(link.score, 4),
            )
            for link in sorted(group.links, key=lambda x: (x.from_event, x.to_event))
        ],
        merged_into=group.merged_into,
    )
