import { coversWallClock, playerTimeToWallClock, wallClockToPlayerTime } from './programDateTime';

/** How far one camera's picture may be from the shared playhead before it is pulled back (P6-J4:
 * synchronized playback, drift <= 300 ms). */
export const DRIFT_LIMIT_MS = 300;

/** What each view must do so that all of them show `masterMs`.
 *
 * `views`: `[{ key, fragments, currentTime }]` — hls.js fragments of that camera's playlist and its
 * `video.currentTime` (player seconds). Returns `[{ key, state, driftMs, playerTime }]`:
 *   - `loading`: no playlist yet — nothing to do;
 *   - `gap`: the camera recorded nothing at `masterMs` (a real gap, not a slow download) — pause it
 *     and say so rather than showing the footage that follows the gap;
 *   - `ok`: within `limitMs` of the playhead;
 *   - `seek`: further off (`driftMs` > 0 is ahead of the playhead) — set `currentTime` to `playerTime`.
 */
export function planSync(masterMs, views, limitMs = DRIFT_LIMIT_MS) {
  return views.map(({ key, fragments, currentTime }) => {
    if (!fragments || fragments.length === 0) return { key, state: 'loading', driftMs: 0 };
    if (!coversWallClock(fragments, masterMs)) return { key, state: 'gap', driftMs: 0 };
    const shown = playerTimeToWallClock(fragments, currentTime ?? 0);
    const driftMs = shown == null ? 0 : shown - masterMs;
    if (Math.abs(driftMs) <= limitMs) return { key, state: 'ok', driftMs };
    return { key, state: 'seek', driftMs, playerTime: wallClockToPlayerTime(fragments, masterMs) };
  });
}

/** The playback rate that closes a small gap smoothly instead of waiting for a seek: slow down a
 * picture that is ahead of the playhead (`driftMs` > 0), speed up one that is behind. Within 25 ms
 * it plays at 1; between 25 and 60 ms it keeps whatever it was doing (so it does not flap around
 * the edge); the further off, the stronger the nudge — 5 % up to 150 ms, 10 % beyond, until the
 * drift limit takes over with a seek. */
export function rateFor(driftMs, currentRate = 1) {
  const size = Math.abs(driftMs);
  if (size < 25) return 1;
  if (size <= 60) return currentRate;
  const strength = size <= 150 ? 0.05 : 0.1;
  return driftMs > 0 ? 1 - strength : 1 + strength;
}

/** The playhead after `dtMs` of real time. It stands still while a view that has footage is still
 * buffering (the others wait for it instead of running ahead) and stops at `endMs`. */
export function advancePlayhead({ masterMs, dtMs, playing, buffering, endMs }) {
  if (!playing || buffering) return masterMs;
  return Math.min(masterMs + dtMs, endMs);
}

/** The phase spans that fall inside `[startMs, endMs]`, as `{ phase, startMs, endMs }` clipped to
 * it; spans outside or empty are dropped. */
export function clipPhases(timeline, startMs, endMs) {
  return (timeline ?? [])
    .map((p) => ({
      phase: p.phase,
      startMs: Math.max(Date.parse(p.start), startMs),
      endMs: Math.min(Date.parse(p.end), endMs),
    }))
    .filter((p) => p.endMs > p.startMs);
}

/** The phase holding `ms` (the last one starting at or before it), or null. */
export function phaseAt(spans, ms) {
  let found = null;
  for (const s of spans) if (ms >= s.startMs && ms < s.endMs) found = s.phase;
  return found;
}
