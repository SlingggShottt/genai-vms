import { describe, expect, it } from 'vitest';
import { formatSeconds, hourSeries, shiftDay } from './lib';

describe('report helpers', () => {
  it('formats response times', () => {
    expect(formatSeconds(null)).toBe('no data');
    expect(formatSeconds(42)).toBe('42 s');
    expect(formatSeconds(125)).toBe('2 min 5 s');
    expect(formatSeconds(3660)).toBe('1 h 1 min');
  });

  it('fills all 24 hours', () => {
    const series = hourSeries({ 12: 6 });
    expect(series).toHaveLength(24);
    expect(series[12]).toEqual({ hour: '12', value: 6 });
    expect(series[0].value).toBe(0);
  });

  it('moves a day across a month boundary', () => {
    expect(shiftDay('2026-10-01', -1)).toBe('2026-09-30');
  });
});
