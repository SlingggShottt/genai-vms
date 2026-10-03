import { z } from 'zod';

/** Response shapes of services/api's topology endpoints (the user-facing name is "camera links").
 * The fixtures in `./fixtures` are generated from the api's own response models
 * (services/api/tests/unit/test_frontend_fixtures.py).
 */
export const EDGE_TYPES = ['overlap', 'transit'];
export const EDGE_TYPE_LABELS = { overlap: 'Overlap', transit: 'Transit' };

// The api's limits (services/api/src/api/domain/topology.py); the form checks them first so the
// person is told before sending, and the api still has the last word.
export const MAX_TRANSIT_S = 3600;
export const MAX_TOLERANCE_S = 600;
export const DEFAULT_TOLERANCE_S = 5;

const isoTime = z.string().datetime({ offset: true });

/** @typedef {z.infer<typeof edgeSchema>} CameraLink */
export const edgeSchema = z.object({
  id: z.string(),
  // `core.cameras.id` UUIDs, not camera codes.
  from_camera_id: z.string(),
  to_camera_id: z.string(),
  edge_type: z.enum(EDGE_TYPES),
  min_s: z.number().nullable(),
  max_s: z.number().nullable(),
  tolerance_s: z.number().nullable(),
  bidirectional: z.boolean(),
  created_at: isoTime,
});

export const edgesPageSchema = z.object({ items: z.array(edgeSchema) });
