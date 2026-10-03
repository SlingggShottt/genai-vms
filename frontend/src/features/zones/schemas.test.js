import { describe, expect, it } from 'vitest';
import zone from './fixtures/zone.json';
import scheduled from './fixtures/zone_scheduled.json';
import page from './fixtures/zones_page.json';
import { ZONE_TYPES, zoneSchema, zonesPageSchema } from './schemas';

describe('zone schemas against what the api sends', () => {
  it('accepts a zone with no schedule', () => {
    const parsed = zoneSchema.parse(zone);
    expect(parsed.schedule).toBeNull();
    expect(parsed.polygon).toHaveLength(4);
    expect(parsed.polygon[0]).toEqual([0.12, 0.3]);
  });

  it('accepts a zone with a schedule that crosses midnight', () => {
    const parsed = zoneSchema.parse(scheduled);
    expect(parsed.zone_type).toBe('restricted');
    expect(parsed.schedule).toEqual({
      start_time: '22:00',
      end_time: '06:00',
      days: ['mon', 'tue', 'wed', 'thu', 'fri'],
    });
  });

  it('accepts a page of zones', () => {
    expect(zonesPageSchema.parse(page).items.map((z) => z.name)).toEqual([
      'Loading bay',
      'Staff yard',
    ]);
  });

  it('knows every zone type the api has', () => {
    // The api's enum: libs/vms_db ZoneType.
    expect(ZONE_TYPES).toEqual(['generic', 'restricted', 'entrance', 'exit']);
  });

  it.each([
    ['an unknown zone type', { ...zone, zone_type: 'secret' }],
    ['a point with three numbers', { ...zone, polygon: [[0.1, 0.2, 0.3]] }],
    ['a point that is not numbers', { ...zone, polygon: [['a', 'b']] }],
    [
      'a schedule with a bad time',
      { ...scheduled, schedule: { ...scheduled.schedule, start_time: '10pm' } },
    ],
    [
      'a schedule with a bad day',
      { ...scheduled, schedule: { ...scheduled.schedule, days: ['someday'] } },
    ],
    ['a missing name', { ...zone, name: undefined }],
    ['a creation time with no timezone', { ...zone, created_at: '2026-10-05T09:00:00' }],
  ])('rejects %s', (_label, bad) => {
    expect(zoneSchema.safeParse(bad).success).toBe(false);
  });
});
