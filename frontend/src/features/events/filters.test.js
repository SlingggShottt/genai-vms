import { describe, expect, it } from 'vitest';
import {
  EMPTY_FILTERS,
  apiFilters,
  filtersFromSearch,
  hasFilters,
  parseLocal,
  rangeError,
  searchFromFilters,
} from './filters';

const search = (qs) => new URLSearchParams(qs);

describe('filtersFromSearch', () => {
  it('reads every filter from the url', () => {
    expect(
      filtersFromSearch(
        search('status=open&severity=high&camera=cam02&from=2026-10-05T10:00&to=2026-10-05T11:00'),
      ),
    ).toEqual({
      status: 'open',
      severity: 'high',
      camera: 'cam02',
      from: '2026-10-05T10:00',
      to: '2026-10-05T11:00',
    });
  });

  it('is "any" for a missing filter', () => {
    expect(filtersFromSearch(search(''))).toEqual(EMPTY_FILTERS);
  });

  it('treats an unknown status or severity as "any" rather than sending it to the api', () => {
    const filters = filtersFromSearch(search('status=closed&severity=urgent'));
    expect(filters.status).toBe('');
    expect(filters.severity).toBe('');
  });
});

describe('searchFromFilters', () => {
  it('writes only the filters that are set, and round-trips', () => {
    const filters = { ...EMPTY_FILTERS, status: 'acknowledged', camera: 'cam04' };
    const params = searchFromFilters(filters);
    expect(params.toString()).toBe('status=acknowledged&camera=cam04');
    expect(filtersFromSearch(params)).toEqual(filters);
  });

  it('is empty when nothing is set', () => {
    expect(searchFromFilters(EMPTY_FILTERS).toString()).toBe('');
  });
});

describe('hasFilters', () => {
  it('is true as soon as any filter is set', () => {
    expect(hasFilters(EMPTY_FILTERS)).toBe(false);
    expect(hasFilters({ ...EMPTY_FILTERS, to: '2026-10-05T10:00' })).toBe(true);
  });
});

describe('rangeError and parseLocal', () => {
  it('accepts an open-ended or ordered range', () => {
    expect(rangeError(EMPTY_FILTERS)).toBeNull();
    expect(rangeError({ from: '2026-10-05T10:00', to: '' })).toBeNull();
    expect(rangeError({ from: '', to: '2026-10-05T10:00' })).toBeNull();
    expect(rangeError({ from: '2026-10-05T10:00', to: '2026-10-05T10:01' })).toBeNull();
  });

  it('says what is wrong with a backwards or equal range, or a bad date', () => {
    expect(rangeError({ from: '2026-10-05T11:00', to: '2026-10-05T10:00' })).toBe(
      'End must be after start.',
    );
    expect(rangeError({ from: '2026-10-05T10:00', to: '2026-10-05T10:00' })).toBe(
      'End must be after start.',
    );
    expect(rangeError({ from: 'garbage', to: '' })).toBe('Start is not a valid date and time.');
    expect(rangeError({ from: '', to: 'garbage' })).toBe('End is not a valid date and time.');
  });

  it('parseLocal gives a Date or null', () => {
    expect(parseLocal('')).toBeNull();
    expect(parseLocal('nope')).toBeNull();
    expect(parseLocal('2026-10-05T10:00')).toBeInstanceOf(Date);
  });
});

describe('apiFilters', () => {
  it('turns the filters into the alerts query', () => {
    const result = apiFilters({
      status: 'open',
      severity: 'critical',
      camera: 'cam02',
      from: '2026-10-05T10:00',
      to: '2026-10-05T11:00',
    });
    expect(result.status).toEqual(['open']);
    expect(result.severity).toEqual(['critical']);
    expect(result.camera_id).toBe('cam02');
    expect(result.start).toBe(new Date('2026-10-05T10:00').toISOString());
    expect(result.end).toBe(new Date('2026-10-05T11:00').toISOString());
  });

  it('sends nothing for "any"', () => {
    expect(apiFilters(EMPTY_FILTERS)).toEqual({
      status: [],
      severity: [],
      camera_id: undefined,
      start: undefined,
      end: undefined,
    });
  });

  it('drops an invalid range instead of sending what the api would reject with 400', () => {
    const result = apiFilters({
      ...EMPTY_FILTERS,
      from: '2026-10-05T12:00',
      to: '2026-10-05T10:00',
    });
    expect(result.start).toBeUndefined();
    expect(result.end).toBeUndefined();
  });
});
