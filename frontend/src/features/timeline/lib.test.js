import { describe, expect, it } from 'vitest';
import {
  linkedEventIds,
  pct,
  searchInRangeHref,
  selectionRange,
  span,
  tickStep,
  ticks,
} from './lib';

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

describe('linked events', () => {
  it('collects the events every group links, whichever group', () => {
    const groups = [{ event_ids: ['a', 'b'] }, { event_ids: ['b', 'c'] }, { event_ids: [] }];
    expect(linkedEventIds(groups)).toEqual(new Set(['a', 'b', 'c']));
  });

  it('is empty when nothing is linked', () => {
    expect(linkedEventIds([]).size).toBe(0);
  });
});

describe('searchInRangeHref', () => {
  it('carries the camera and the period as the search page reads them', () => {
    const href = searchInRangeHref({
      camera: 'cam02',
      start: Date.UTC(2026, 9, 25, 9, 30),
      end: Date.UTC(2026, 9, 25, 9, 45),
    });
    const url = new URL(href, 'http://x');
    expect(url.pathname).toBe('/search');
    expect(url.searchParams.get('camera')).toBe('cam02');
    expect(url.searchParams.get('start')).toBe('2026-10-25T09:30:00.000Z');
    expect(url.searchParams.get('end')).toBe('2026-10-25T09:45:00.000Z');
  });
});
