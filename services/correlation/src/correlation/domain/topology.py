"""The camera graph as the engine uses it: look up the edges joining two cameras, and ask how
long after an event on some cameras another camera could still produce a linkable one."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from vms_common.contracts.topology import TopologyEdgeInternal


class Topology:
    def __init__(self, edges: Iterable[TopologyEdgeInternal] = ()) -> None:
        self._edges = list(edges)
        self._between: dict[frozenset[str], list[TopologyEdgeInternal]] = defaultdict(list)
        self._incident: dict[str, list[TopologyEdgeInternal]] = defaultdict(list)
        for edge in self._edges:
            self._between[frozenset((edge.from_camera_id, edge.to_camera_id))].append(edge)
            self._incident[edge.from_camera_id].append(edge)
            self._incident[edge.to_camera_id].append(edge)

    @property
    def edges(self) -> list[TopologyEdgeInternal]:
        return list(self._edges)

    def edges_between(self, camera_a: str, camera_b: str) -> list[TopologyEdgeInternal]:
        """Edges joining the two cameras, in either direction."""
        return list(self._between.get(frozenset((camera_a, camera_b)), ()))

    def max_window_s(self, cameras: Iterable[str]) -> float:
        """The longest a linkable event could still arrive after an event on any of `cameras`:
        the longest transit window, or twice the largest overlap tolerance (each window is
        widened by it), over the edges touching those cameras. 0 for a camera with no edges —
        nothing else can ever link to it."""
        longest = 0.0
        for camera in set(cameras):
            for edge in self._incident.get(camera, ()):
                if edge.edge_type == "transit":
                    longest = max(longest, edge.max_s or 0.0)
                else:
                    longest = max(longest, 2 * (edge.tolerance_s or 0.0))
        return longest
