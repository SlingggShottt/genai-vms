/** Player time (hls.js's own continuous seconds timeline) <-> wall-clock
 * time (epoch ms), via each fragment's `#EXT-X-PROGRAM-DATE-TIME`
 * (design_architecture.md §9's "Player time <-> wall-clock mapping").
 * hls.js parses that tag itself into `fragment.programDateTime`; this
 * module just does the arithmetic, pure and independent of hls.js's own
 * types so it's plain-object testable.
 *
 * A `fragments` array is `hls.levels[0].details.fragments` — segments in
 * playback order, each `{ start, duration, programDateTime }`.
 * `start`/`duration` are always contiguous in player time regardless of a
 * `#EXT-X-DISCONTINUITY` (P2-J3's gap marker) in the playlist, but
 * `programDateTime` is NOT contiguous across one — there's a real gap in
 * wall-clock time with no fragment covering it. `wallClockToPlayerTime`
 * handles that by snapping forward to the next fragment that does exist.
 */

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function locateByPlayerTime(fragments, playerTime) {
  const first = fragments[0];
  const last = fragments[fragments.length - 1];
  const clamped = clamp(playerTime, first.start, last.start + last.duration);
  for (const frag of fragments) {
    const fragEnd = frag.start + frag.duration;
    if (clamped >= frag.start && (clamped < fragEnd || frag === last)) {
      return { frag, offsetS: clamped - frag.start };
    }
  }
  return null; // unreachable given the clamp above; defensive only
}

function locateByWallClock(fragments, wallClockMs) {
  const withPdt = (fragments ?? []).filter((f) => f.programDateTime != null);
  if (withPdt.length === 0) return null;

  const first = withPdt[0];
  const last = withPdt[withPdt.length - 1];
  const lastEndMs = last.programDateTime + last.duration * 1000;

  if (wallClockMs <= first.programDateTime) return { frag: first, offsetMs: 0 };
  if (wallClockMs >= lastEndMs) return { frag: last, offsetMs: last.duration * 1000 };

  for (const frag of withPdt) {
    const fragEndMs = frag.programDateTime + frag.duration * 1000;
    if (wallClockMs >= frag.programDateTime && wallClockMs < fragEndMs) {
      return { frag, offsetMs: wallClockMs - frag.programDateTime };
    }
  }
  // Inside a real gap between two fragments (a genuine recording gap, not
  // just a discontinuity) — snap forward to the next available footage.
  const next = withPdt.find((f) => f.programDateTime > wallClockMs);
  return { frag: next, offsetMs: 0 };
}

/** `playerTime` (seconds) -> wall-clock epoch ms, or `null` if `fragments`
 * is empty or the matching fragment has no PDT.
 */
export function playerTimeToWallClock(fragments, playerTime) {
  if (!fragments || fragments.length === 0) return null;
  const located = locateByPlayerTime(fragments, playerTime);
  if (!located || located.frag.programDateTime == null) return null;
  return located.frag.programDateTime + located.offsetS * 1000;
}

/** Wall-clock epoch ms -> `playerTime` (seconds), or `null` if no fragment
 * carries PDT data.
 */
export function wallClockToPlayerTime(fragments, wallClockMs) {
  const located = locateByWallClock(fragments, wallClockMs);
  if (!located) return null;
  return located.frag.start + located.offsetMs / 1000;
}

/** True when some fragment covers `wallClockMs`: there is footage at that moment. (Unlike
 * `wallClockToPlayerTime`, which snaps across a gap to the next footage, this says there is none.)
 */
export function coversWallClock(fragments, wallClockMs) {
  return (fragments ?? []).some(
    (f) =>
      f.programDateTime != null &&
      wallClockMs >= f.programDateTime &&
      wallClockMs < f.programDateTime + f.duration * 1000,
  );
}
