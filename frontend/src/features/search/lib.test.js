import { describe, expect, it } from 'vitest';
import { periodFromParams } from './lib';

const params = (q) => new URLSearchParams(q);

describe('periodFromParams', () => {
  it('reads a period from a link and gives it back as ISO times', () => {
    expect(
      periodFromParams(params('start=2026-10-25T09:30:00%2B05:30&end=2026-10-25T10:00:00%2B05:30')),
    ).toEqual({ start: '2026-10-25T04:00:00.000Z', end: '2026-10-25T04:30:00.000Z' });
  });

  it.each([
    ['', 'nothing in the link'],
    ['start=2026-10-25T09:30:00Z', 'only a start'],
    ['end=2026-10-25T09:30:00Z', 'only an end'],
    ['start=yesterday&end=today', 'words, not times'],
    ['start=2026-10-25T10:00:00Z&end=2026-10-25T09:00:00Z', 'an end before the start'],
    ['start=2026-10-25T10:00:00Z&end=2026-10-25T10:00:00Z', 'no length'],
  ])('is no period for %s (%s)', (query) => {
    expect(periodFromParams(params(query))).toBeNull();
  });
});
