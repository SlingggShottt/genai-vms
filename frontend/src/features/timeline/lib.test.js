import { describe, expect, it } from 'vitest';
import { pct, selectionRange, span, tickStep, ticks } from './lib';

describe('timeline geometry', () => {
  it('places instants within the period and clamps those outside it', () => {
    expect(pct(50, 0, 100)).toBe(50);
    expect(pct(-10, 0, 100)).toBe(0);
    expect(pct(500, 0, 100)).toBe(100);
  });

  it('never draws a bar thinner than the minimum', () => {
    expect(span(10, 10, 0, 100).width).toBeGreaterThan(0);
    expect(span(10, 30, 0, 100)).toEqual({ left: 10, width: 20 });
  });

  it('turns a drag in either direction into an ordered period', () => {
    expect(selectionRange(0.8, 0.2, 1000, 2000)).toEqual({ start: 1200, end: 1800 });
  });

  it('chooses a tick step that gives a readable number of labels', () => {
    expect(tickStep(3600e3)).toBe(10 * 60e3);
    const hour = 3600e3;
    const t = ticks(0, 6 * hour);
    expect(t.length).toBeGreaterThanOrEqual(4);
    expect(t.length).toBeLessThanOrEqual(11);
  });
});
