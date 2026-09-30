import { useCallback, useMemo, useRef } from 'react';
import { formatClock } from '@/lib/time';

const STEP_MS = 1000;
const BIG_STEP_MS = 10_000;

/** Timeline scrubber v1 (docs/style_guide.md §B.6, reduced for P2-J5 —
 * event markers, phase band and correlation links land with the
 * event/investigation stories that have the data for them). One lane:
 * density sparkline (`--text-muted` at 40% opacity) plus a 2px `--accent`
 * playhead. Drag or click to scrub; arrow keys step 1s, Shift+arrow 10s
 * (§B.6's interaction spec).
 *
 * `buckets` are `/recordings/{camera}/density` rows; `rangeStart`/
 * `rangeEnd` are `Date`s bounding the whole scrubber; `playheadMs` is the
 * current wall-clock position (epoch ms); `onScrub(ms)` fires on every
 * drag/click/keyboard move with the new wall-clock position, already
 * clamped to `[rangeStart, rangeEnd]`.
 */
export function TimelineScrubber({ buckets, rangeStart, rangeEnd, playheadMs, onScrub }) {
  const trackRef = useRef(null);

  const rangeStartMs = rangeStart.getTime();
  const rangeEndMs = rangeEnd.getTime();
  const rangeSpanMs = Math.max(rangeEndMs - rangeStartMs, 1);

  const maxCount = useMemo(() => Math.max(1, ...buckets.map((b) => b.count)), [buckets]);

  const clampMs = useCallback(
    (ms) => Math.min(Math.max(ms, rangeStartMs), rangeEndMs),
    [rangeStartMs, rangeEndMs],
  );

  function msFromClientX(clientX) {
    const track = trackRef.current;
    if (!track) return playheadMs;
    const rect = track.getBoundingClientRect();
    const ratio = rect.width > 0 ? (clientX - rect.left) / rect.width : 0;
    return clampMs(rangeStartMs + ratio * rangeSpanMs);
  }

  function handlePointerDown(event) {
    event.currentTarget.setPointerCapture(event.pointerId);
    onScrub(msFromClientX(event.clientX));
  }

  function handlePointerMove(event) {
    if (event.buttons !== 1) return; // drag only while the primary button is held
    onScrub(msFromClientX(event.clientX));
  }

  function handleKeyDown(event) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const step = event.shiftKey ? BIG_STEP_MS : STEP_MS;
    const direction = event.key === 'ArrowRight' ? 1 : -1;
    onScrub(clampMs(playheadMs + direction * step));
  }

  const clampedPlayheadMs = clampMs(playheadMs);
  const playheadRatio = (clampedPlayheadMs - rangeStartMs) / rangeSpanMs;

  return (
    <div className="flex flex-col gap-1">
      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label="Playback timeline"
        aria-valuemin={rangeStartMs}
        aria-valuemax={rangeEndMs}
        aria-valuenow={clampedPlayheadMs}
        aria-valuetext={formatClock(new Date(clampedPlayheadMs))}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onKeyDown={handleKeyDown}
        className="relative h-16 cursor-pointer select-none rounded-panel border border-rule bg-surface"
      >
        <div className="absolute inset-0 flex items-end gap-px px-1 pb-1" aria-hidden="true">
          {buckets.map((bucket) => (
            <div
              key={bucket.start_ts}
              className="min-h-[2px] flex-1 rounded-[1px] bg-text-muted/40"
              style={{ height: `${Math.max(2, (bucket.count / maxCount) * 100)}%` }}
            />
          ))}
        </div>

        <div
          className="pointer-events-none absolute top-0 h-full w-0.5 bg-accent"
          style={{ left: `${playheadRatio * 100}%` }}
          aria-hidden="true"
        />
      </div>

      <div className="flex justify-between text-xs tabular-nums text-text-muted">
        <span>{formatClock(rangeStart)}</span>
        <span className="font-medium text-text">{formatClock(new Date(clampedPlayheadMs))}</span>
        <span>{formatClock(rangeEnd)}</span>
      </div>
    </div>
  );
}
