"""Adaptive frame sampling — P2-D1 AC: "1 fps when consumer lag > 60 s,
back to default when < 10 s." Needs hysteresis (a single threshold would
flap right at the boundary), so this is a small stateful class rather
than a pure function — still fully unit-testable by feeding it a lag
sequence.
"""

from __future__ import annotations

DEFAULT_FPS = 2.0
DEGRADED_FPS = 1.0
DEGRADE_THRESHOLD_S = 60.0
RECOVER_THRESHOLD_S = 10.0


class AdaptiveSampler:
    """Tracks degraded/normal sampling state for one camera's consumer lag."""

    def __init__(
        self,
        *,
        default_fps: float = DEFAULT_FPS,
        degraded_fps: float = DEGRADED_FPS,
        degrade_threshold_s: float = DEGRADE_THRESHOLD_S,
        recover_threshold_s: float = RECOVER_THRESHOLD_S,
    ) -> None:
        if recover_threshold_s >= degrade_threshold_s:
            raise ValueError("recover_threshold_s must be < degrade_threshold_s")
        self._default_fps = default_fps
        self._degraded_fps = degraded_fps
        self._degrade_threshold_s = degrade_threshold_s
        self._recover_threshold_s = recover_threshold_s
        self._degraded = False

    @property
    def degraded(self) -> bool:
        return self._degraded

    def sample_fps(self, consumer_lag_s: float) -> float:
        """Feed the current consumer lag; returns the fps to sample at now."""
        if self._degraded:
            if consumer_lag_s < self._recover_threshold_s:
                self._degraded = False
        elif consumer_lag_s > self._degrade_threshold_s:
            self._degraded = True
        return self._degraded_fps if self._degraded else self._default_fps
