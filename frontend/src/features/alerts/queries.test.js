import { describe, expect, it } from 'vitest';
import { PAGE_SIZE, TRAY_FILTERS, alertsQueryString } from './queries';

const parse = (qs) => new URLSearchParams(qs);

describe('alertsQueryString', () => {
  it('always carries a limit', () => {
    expect(parse(alertsQueryString()).get('limit')).toBe(String(PAGE_SIZE));
  });

  it('repeats list parameters, as the api expects (status=…&status=…)', () => {
    const params = parse(
      alertsQueryString({ status: ['open', 'resolved'], severity: ['high', 'critical'] }),
    );
    expect(params.getAll('status')).toEqual(['open', 'resolved']);
    expect(params.getAll('severity')).toEqual(['high', 'critical']);
  });

  it('leaves out empty values rather than sending blanks', () => {
    const qs = alertsQueryString({ status: [], camera_id: '', group_id: undefined, start: '' });
    expect(qs).toBe(`?limit=${PAGE_SIZE}`);
  });

  it('passes the camera code, group, window and cursor through', () => {
    const params = parse(
      alertsQueryString({
        camera_id: 'cam02',
        group_id: 'g1',
        start: '2026-10-05T00:00:00.000Z',
        end: '2026-10-06T00:00:00.000Z',
        limit: 10,
        cursor: 'c1',
      }),
    );
    expect(Object.fromEntries(params)).toEqual({
      camera_id: 'cam02',
      group_id: 'g1',
      start: '2026-10-05T00:00:00.000Z',
      end: '2026-10-06T00:00:00.000Z',
      limit: '10',
      cursor: 'c1',
    });
  });

  it('encodes values that need it', () => {
    expect(alertsQueryString({ camera_id: 'cam 02&x' })).toContain('camera_id=cam+02%26x');
  });

  it('the tray asks for what is still waiting for a person', () => {
    expect(parse(alertsQueryString(TRAY_FILTERS)).getAll('status')).toEqual([
      'open',
      'acknowledged',
    ]);
  });
});
