import { describe, expect, it } from 'vitest';
import { coversWallClock } from './programDateTime';
import { advancePlayhead, clipPhases, DRIFT_LIMIT_MS, phaseAt, planSync, rateFor } from './sync';

const T0 = Date.parse('2026-10-06T12:00:00.000Z');
// Two 10 s segments with a 20 s hole between them in wall-clock time (a recording gap).
const FRAGS = [
  { start: 0, duration: 10, programDateTime: T0 },
  { start: 10, duration: 10, programDateTime: T0 + 30_000 },
];

describe('coversWallClock', () => {
  it('is true inside a fragment and false in a gap, before and after', () => {
    expect(coversWallClock(FRAGS, T0)).toBe(true);
    expect(coversWallClock(FRAGS, T0 + 9_999)).toBe(true);
    expect(coversWallClock(FRAGS, T0 + 10_000)).toBe(false); // the end is exclusive
    expect(coversWallClock(FRAGS, T0 + 20_000)).toBe(false); // in the hole
    expect(coversWallClock(FRAGS, T0 + 30_000)).toBe(true);
    expect(coversWallClock(FRAGS, T0 - 1)).toBe(false);
    expect(coversWallClock(FRAGS, T0 + 40_000)).toBe(false);
  });

  it('is false without footage or without wall-clock data', () => {
    expect(coversWallClock([], T0)).toBe(false);
    expect(coversWallClock(undefined, T0)).toBe(false);
    expect(coversWallClock([{ start: 0, duration: 10, programDateTime: null }], T0)).toBe(false);
  });
});

describe('planSync', () => {
  const view = (key, currentTime, fragments = FRAGS) => ({ key, fragments, currentTime });

  it('leaves a view that is within the limit alone and reports its drift', () => {
    const [a] = planSync(T0 + 4_000, [view('a', 4.2)]);
    expect(a).toMatchObject({ state: 'ok' });
    expect(a.driftMs).toBeCloseTo(200);
  });

  it('allows exactly the limit, seeks beyond it', () => {
    const edge = 4 + DRIFT_LIMIT_MS / 1000;
    expect(planSync(T0 + 4_000, [view('a', edge)])[0].state).toBe('ok');
    expect(planSync(T0 + 4_000, [view('a', edge + 0.05)])[0].state).toBe('seek');
    expect(planSync(T0 + 4_000, [view('a', 4 - edge - 0.05)])[0].state).toBe('seek');
  });

  it('says where to seek, and which way it was off', () => {
    const [ahead] = planSync(T0 + 4_000, [view('a', 7)]);
    expect(ahead).toMatchObject({ state: 'seek', playerTime: 4 });
    expect(ahead.driftMs).toBeCloseTo(3_000);
    const [behind] = planSync(T0 + 34_000, [view('a', 11)]);
    expect(behind.state).toBe('seek');
    expect(behind.playerTime).toBe(14); // the second fragment starts at player second 10
    expect(behind.driftMs).toBeLessThan(0);
  });

  it('calls a recording gap a gap instead of showing the footage after it', () => {
    expect(planSync(T0 + 20_000, [view('a', 10)])[0]).toEqual({
      key: 'a',
      state: 'gap',
      driftMs: 0,
    });
  });

  it('waits for a view whose playlist has not loaded', () => {
    expect(planSync(T0, [{ key: 'a', fragments: [], currentTime: 0 }])[0].state).toBe('loading');
    expect(planSync(T0, [{ key: 'a', fragments: undefined, currentTime: 0 }])[0].state).toBe(
      'loading',
    );
  });

  it('plans each camera on its own recordings', () => {
    const other = [{ start: 0, duration: 60, programDateTime: T0 + 15_000 }];
    const plan = planSync(T0 + 20_000, [view('a', 10), view('b', 5, other)]);
    expect(plan.map((p) => [p.key, p.state])).toEqual([
      ['a', 'gap'],
      ['b', 'ok'],
    ]);
  });
});

describe('advancePlayhead', () => {
  const base = { masterMs: 1000, dtMs: 200, playing: true, buffering: false, endMs: 5000 };
  it('moves with real time while playing', () => {
    expect(advancePlayhead(base)).toBe(1200);
  });
  it('stands still when paused or while a view buffers', () => {
    expect(advancePlayhead({ ...base, playing: false })).toBe(1000);
    expect(advancePlayhead({ ...base, buffering: true })).toBe(1000);
  });
  it('stops at the end of the range', () => {
    expect(advancePlayhead({ ...base, masterMs: 4900 })).toBe(5000);
  });
});

describe('phases', () => {
  const timeline = [
    { phase: 'baseline', start: '2026-10-06T12:00:00Z', end: '2026-10-06T12:00:10Z' },
    { phase: 'action', start: '2026-10-06T12:00:10Z', end: '2026-10-06T12:00:20Z' },
    { phase: 'aftermath', start: '2026-10-06T12:00:20Z', end: '2026-10-06T12:00:20Z' },
  ];
  it('clips spans to the range and drops empty or outside ones', () => {
    const spans = clipPhases(timeline, T0 + 5_000, T0 + 15_000);
    expect(spans).toEqual([
      { phase: 'baseline', startMs: T0 + 5_000, endMs: T0 + 10_000 },
      { phase: 'action', startMs: T0 + 10_000, endMs: T0 + 15_000 },
    ]);
    expect(clipPhases(timeline, T0 + 30_000, T0 + 40_000)).toEqual([]);
    expect(clipPhases(undefined, T0, T0 + 1)).toEqual([]);
  });
  it('finds the phase at a moment', () => {
    const spans = clipPhases(timeline, T0, T0 + 20_000);
    expect(phaseAt(spans, T0 + 3_000)).toBe('baseline');
    expect(phaseAt(spans, T0 + 10_000)).toBe('action'); // a boundary belongs to the later phase
    expect(phaseAt(spans, T0 + 25_000)).toBeNull();
  });
});

describe('rateFor', () => {
  it('plays at normal speed when the picture is in step', () => {
    expect(rateFor(0)).toBe(1);
    expect(rateFor(24, 0.95)).toBe(1);
    expect(rateFor(-24, 1.05)).toBe(1);
  });
  it('slows a picture that is ahead and speeds one that is behind', () => {
    expect(rateFor(100)).toBe(0.95);
    expect(rateFor(-100)).toBe(1.05);
    expect(rateFor(250)).toBe(0.9);
    expect(rateFor(-250)).toBe(1.1);
  });
  it('keeps its rate in the band between, so it does not flap', () => {
    expect(rateFor(40, 0.95)).toBe(0.95);
    expect(rateFor(-40, 1.05)).toBe(1.05);
    expect(rateFor(40, 1)).toBe(1);
  });
  it('uses the stronger nudge only beyond 150 ms', () => {
    expect(rateFor(150)).toBe(0.95);
    expect(rateFor(151)).toBe(0.9);
  });
});
