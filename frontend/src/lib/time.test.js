import { describe, expect, it } from 'vitest';
import { formatAbsolute, formatClock, formatDateTime, formatRelative } from './time';

describe('formatAbsolute', () => {
  // 2026-10-05 04:45:04 UTC is 10:15:04 IST
  const now = new Date('2026-10-05T04:45:04Z');

  it('shows just the IST clock for something that happened today (IST)', () => {
    expect(formatAbsolute(new Date('2026-10-05T04:30:00Z'), now)).toBe('10:00:00');
  });

  it('shows the date and time for an earlier day', () => {
    expect(formatAbsolute(new Date('2026-10-03T08:35:20Z'), now)).toBe('3 Oct, 14:05');
  });

  it('decides "today" by the IST calendar, not UTC', () => {
    // 20:00 UTC on the 4th is 01:30 IST on the 5th: today in IST although it is yesterday in UTC.
    expect(formatAbsolute(new Date('2026-10-04T20:00:00Z'), now)).toBe('01:30:00');
    // 19:00 UTC on the 4th is 00:30 IST on the 5th... and 18:00 UTC is 23:30 IST on the 4th.
    expect(formatAbsolute(new Date('2026-10-04T18:00:00Z'), now)).toBe('4 Oct, 23:30');
  });
});

describe('existing formatters keep their contract', () => {
  it('formats clock and dated times in IST', () => {
    expect(formatClock(new Date('2026-10-05T04:45:04Z'))).toBe('10:15:04');
    expect(formatDateTime(new Date('2026-10-05T04:45:04Z'))).toBe('5 Oct, 10:15');
  });

  it('formats relative times', () => {
    const now = new Date('2026-10-05T10:00:00Z');
    expect(formatRelative(new Date('2026-10-05T09:59:58Z'), now)).toBe('just now');
    expect(formatRelative(new Date('2026-10-05T09:59:00Z'), now)).toBe('1 min ago');
    expect(formatRelative(new Date('2026-10-05T07:00:00Z'), now)).toBe('3 hr ago');
  });
});
