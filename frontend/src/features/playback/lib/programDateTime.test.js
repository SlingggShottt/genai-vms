import { describe, expect, it } from 'vitest';
import { playerTimeToWallClock, wallClockToPlayerTime } from './programDateTime';

const PDT_0 = Date.parse('2026-10-05T10:15:00.000Z');
const PDT_1 = Date.parse('2026-10-05T10:15:10.000Z');

// Mirrors a two-segment playlist: [0,10) and [10,20) player seconds,
// wall-clock 10:15:00 and 10:15:10 respectively (a 10s gap has since been
// closed between them — same shape a `#EXT-X-DISCONTINUITY` playlist gives
// hls.js).
const FRAGMENTS = [
  { start: 0, duration: 10, programDateTime: PDT_0 },
  { start: 10, duration: 10, programDateTime: PDT_1 },
];

describe('playerTimeToWallClock', () => {
  it('maps the start of a fragment to its programDateTime', () => {
    expect(playerTimeToWallClock(FRAGMENTS, 0)).toBe(PDT_0);
    expect(playerTimeToWallClock(FRAGMENTS, 10)).toBe(PDT_1);
  });

  it('maps a mid-fragment time with the right offset', () => {
    expect(playerTimeToWallClock(FRAGMENTS, 4)).toBe(PDT_0 + 4000);
    expect(playerTimeToWallClock(FRAGMENTS, 15)).toBe(PDT_1 + 5000);
  });

  it('clamps a time before the first fragment to the first fragment start', () => {
    expect(playerTimeToWallClock(FRAGMENTS, -5)).toBe(PDT_0);
  });

  it('clamps a time after the last fragment to the last fragment end', () => {
    expect(playerTimeToWallClock(FRAGMENTS, 100)).toBe(PDT_1 + 10_000);
  });

  it('returns null for an empty fragment list', () => {
    expect(playerTimeToWallClock([], 5)).toBeNull();
  });
});

describe('wallClockToPlayerTime', () => {
  it('is the inverse of playerTimeToWallClock at fragment starts', () => {
    expect(wallClockToPlayerTime(FRAGMENTS, PDT_0)).toBe(0);
    expect(wallClockToPlayerTime(FRAGMENTS, PDT_1)).toBe(10);
  });

  it('maps a mid-fragment wall-clock time back to player time', () => {
    expect(wallClockToPlayerTime(FRAGMENTS, PDT_0 + 4000)).toBe(4);
  });

  it('clamps a wall-clock time before the first fragment', () => {
    expect(wallClockToPlayerTime(FRAGMENTS, PDT_0 - 5000)).toBe(0);
  });

  it('clamps a wall-clock time after the last fragment', () => {
    expect(wallClockToPlayerTime(FRAGMENTS, PDT_1 + 50000)).toBe(20);
  });

  it('returns null when no fragment carries programDateTime', () => {
    const noPdt = [{ start: 0, duration: 10, programDateTime: null }];
    expect(wallClockToPlayerTime(noPdt, PDT_0)).toBeNull();
  });

  it('snaps forward to the next fragment when scrubbed into a real recording gap', () => {
    // Player time is still contiguous ([0,10) then [10,20)) even though
    // there's a genuine 5-minute wall-clock gap between the two segments
    // (e.g. a camera reconnect) — this is different from the
    // #EXT-X-DISCONTINUITY case FRAGMENTS above already closed.
    const withGap = [
      { start: 0, duration: 10, programDateTime: PDT_0 },
      { start: 10, duration: 10, programDateTime: PDT_0 + 5 * 60_000 },
    ];
    const midGapMs = PDT_0 + 2 * 60_000; // well inside the gap
    expect(wallClockToPlayerTime(withGap, midGapMs)).toBe(10);
  });
});
