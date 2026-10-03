"""Linking two events (design_architecture.md §7.5).

An edge of the camera graph says whether two events *could* be the same activity; the
temporal fit says how well their timing matches (1.0 in the middle of the edge's window, 0 at
its bounds); the compatibility of the two event types (config) says whether such activities
belong together at all. `score = fit_weight * fit + compat_weight * compat` and a pair links
when it reaches `link_threshold`.

- overlap(A, B, tau): the cameras see the same area. Widen each event's window by tau on both
  sides; they link when the widened windows intersect, i.e. when the gap between the original
  windows is at most 2*tau. fit = 1 when the windows intersect, falling linearly to 0 at 2*tau.
- transit(A -> B, min, max): B is reachable from A. With a = the event on A and b = the event
  on B, they link when start(b) - end(a) lies in [min, max]; fit is 1 at the centre of that
  window and 0 at its bounds. A bidirectional edge also allows the opposite orientation.
"""

from __future__ import annotations

from vms_common.contracts.topology import TopologyEdgeInternal

from correlation.domain.config import CorrelationConfig
from correlation.domain.topology import Topology
from correlation.domain.types import EventRecord, LinkRecord


def overlap_fit(a: EventRecord, b: EventRecord, tolerance_s: float) -> tuple[float, float] | None:
    """(fit, gap_s) for two events on cameras that overlap, or None if too far apart."""
    gap = max(0.0, (max(a.start_ts, b.start_ts) - min(a.end_ts, b.end_ts)).total_seconds())
    if gap == 0:
        return 1.0, 0.0
    if gap > 2 * tolerance_s:
        return None
    return 1.0 - gap / (2 * tolerance_s), gap


def transit_fit(delta_s: float, min_s: float, max_s: float) -> float | None:
    """Fit of a transit time `delta_s` against the window [min_s, max_s]; None if outside it."""
    if not min_s <= delta_s <= max_s:
        return None
    half = (max_s - min_s) / 2
    if half == 0:
        return 1.0
    return max(0.0, 1.0 - abs(delta_s - (min_s + max_s) / 2) / half)


def _candidates(
    edge: TopologyEdgeInternal, new: EventRecord, existing: EventRecord
) -> list[tuple[float, float, LinkRecord]]:
    """(fit, tie-break, link-without-score) for each way `edge` could join the two events."""
    if edge.edge_type == "overlap":
        result = overlap_fit(new, existing, edge.tolerance_s or 0.0)
        if result is None:
            return []
        fit, gap = result
        return [(fit, 0.0, LinkRecord(existing.event_id, new.event_id, "overlap", gap, 0.0))]

    pairs: list[tuple[EventRecord, EventRecord]] = []  # (event on `from`, event on `to`)
    if new.camera_id == edge.from_camera_id and existing.camera_id == edge.to_camera_id:
        pairs.append((new, existing))
    if existing.camera_id == edge.from_camera_id and new.camera_id == edge.to_camera_id:
        pairs.append((existing, new))
    if edge.bidirectional:  # the opposite orientation is valid too
        pairs += [(b, a) for a, b in pairs if (b, a) not in pairs]
    found = []
    for earlier_side, later_side in pairs:
        delta = (later_side.start_ts - earlier_side.end_ts).total_seconds()
        fit = transit_fit(delta, edge.min_s or 0.0, edge.max_s or 0.0)
        if fit is not None:
            link = LinkRecord(earlier_side.event_id, later_side.event_id, "transit", delta, 0.0)
            found.append((fit, 0.0, link))
    return found


def best_link(
    new: EventRecord, existing: EventRecord, topology: Topology, config: CorrelationConfig
) -> LinkRecord | None:
    """The strongest link between two events that clears the threshold, or None.

    Events on one camera never link (nothing in the graph joins a camera to itself), and a
    pair of event types the config calls incompatible never links.
    """
    if new.camera_id == existing.camera_id:
        return None
    compat = config.compat(new.event_type, existing.event_type)
    if compat <= 0:
        return None
    best: LinkRecord | None = None
    for edge in topology.edges_between(new.camera_id, existing.camera_id):
        for fit, _, link in _candidates(edge, new, existing):
            score = config.fit_weight * fit + config.compat_weight * compat
            if score >= config.link_threshold and (best is None or score > best.score):
                best = LinkRecord(
                    link.from_event, link.to_event, link.edge_type, link.delta_s, score
                )
    return best
