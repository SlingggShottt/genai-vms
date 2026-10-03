import { z } from 'zod';

/** Response shapes of services/api's zone endpoints. The fixtures in `./fixtures` are generated
 * from the api's own response models (services/api/tests/unit/test_frontend_fixtures.py), so
 * these schemas are tested against what the api really sends.
 */
export const ZONE_TYPES = ['generic', 'restricted', 'entrance', 'exit'];
export const ZONE_TYPE_LABELS = {
  generic: 'General',
  restricted: 'Restricted',
  entrance: 'Entrance',
  exit: 'Exit',
};

export const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
export const DAY_LABELS = {
  mon: 'Mon',
  tue: 'Tue',
  wed: 'Wed',
  thu: 'Thu',
  fri: 'Fri',
  sat: 'Sat',
  sun: 'Sun',
};

const isoTime = z.string().datetime({ offset: true });

export const zoneTypeSchema = z.enum(ZONE_TYPES);

export const scheduleSchema = z.object({
  start_time: z.string().regex(/^\d{2}:\d{2}$/),
  end_time: z.string().regex(/^\d{2}:\d{2}$/),
  days: z.array(z.enum(DAYS)),
});

/** @typedef {z.infer<typeof zoneSchema>} Zone */
export const zoneSchema = z.object({
  id: z.string(),
  // The camera's `core.cameras.id` (a UUID), not its code.
  camera_id: z.string(),
  name: z.string(),
  zone_type: zoneTypeSchema,
  polygon: z.array(z.tuple([z.number(), z.number()])),
  schedule: scheduleSchema.nullable(),
  created_at: isoTime,
});

export const zonesPageSchema = z.object({ items: z.array(zoneSchema) });
