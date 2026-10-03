import { z } from 'zod';

/** Response shapes of services/api's alerts and correlations endpoints. The fixtures in
 * `./fixtures` are generated from the api's own response models
 * (services/api/tests/unit/test_frontend_fixtures.py), so these schemas are tested against
 * what the api really sends.
 */
export const SEVERITIES = ['low', 'medium', 'high', 'critical'];
export const ALERT_STATUSES = ['open', 'acknowledged', 'resolved'];

// The api serialises UTC instants as `…Z`; accept an explicit offset too.
const isoTime = z.string().datetime({ offset: true });

export const severitySchema = z.enum(SEVERITIES);
export const alertStatusSchema = z.enum(ALERT_STATUSES);

export const alertGroupSchema = z.object({
  id: z.string(),
  status: z.enum(['open', 'closed']),
  event_count: z.number().int(),
  camera_ids: z.array(z.string()),
  max_severity: severitySchema,
  start_ts: isoTime,
  end_ts: isoTime,
});

/** @typedef {z.infer<typeof alertSchema>} Alert */
export const alertSchema = z.object({
  id: z.string(),
  event_id: z.string(),
  site_id: z.string(),
  camera_code: z.string(),
  camera_id: z.string().nullable(),
  event_type: z.string(),
  severity: severitySchema,
  title: z.string(),
  caption: z.string().nullable(),
  rule_id: z.string(),
  zone_id: z.string().nullable(),
  verification_status: z.enum(['verified', 'skipped']),
  confidence: z.number().nullable(),
  start_ts: isoTime,
  end_ts: isoTime,
  // Presigned and short-lived; empty on a WebSocket push (fetch GET /alerts/{id} for urls).
  keyframe_urls: z.array(z.string()),
  keyframe_count: z.number().int(),
  group: alertGroupSchema.nullable(),
  status: alertStatusSchema,
  acknowledged_by: z.string().nullable(),
  acknowledged_at: isoTime.nullable(),
  ack_note: z.string().nullable(),
  resolved_by: z.string().nullable(),
  resolved_at: isoTime.nullable(),
  resolve_note: z.string().nullable(),
  created_at: isoTime,
  updated_at: isoTime,
});

export const alertsPageSchema = z.object({
  items: z.array(alertSchema),
  next_cursor: z.string().nullable(),
});

export const correlationMemberSchema = z.object({
  event_id: z.string(),
  camera_id: z.string(),
  event_type: z.string(),
  severity: severitySchema,
  start_ts: isoTime,
  end_ts: isoTime,
});

export const correlationLinkSchema = z.object({
  from_event: z.string(),
  to_event: z.string(),
  edge_type: z.enum(['overlap', 'transit']),
  delta_s: z.number(),
  score: z.number(),
});

export const correlationGroupSchema = z.object({
  id: z.string(),
  site_id: z.string(),
  status: z.enum(['open', 'closed', 'merged']),
  revision: z.number().int(),
  start_ts: isoTime,
  end_ts: isoTime,
  max_severity: severitySchema,
  camera_ids: z.array(z.string()),
  event_types: z.array(z.string()),
  event_ids: z.array(z.string()),
  merged_into: z.string().nullable(),
  created_at: isoTime,
  closed_at: isoTime.nullable(),
});

export const correlationGroupDetailSchema = correlationGroupSchema.extend({
  members: z.array(correlationMemberSchema),
  links: z.array(correlationLinkSchema),
});

/** `{type, data, ts}` — every WebSocket message (services/api/realtime/messages.py). */
export const wsEnvelopeSchema = z.object({
  type: z.string().min(1),
  data: z.record(z.unknown()),
  ts: isoTime,
});

/** Operators and admins see alerts; a viewer gets 403 on `/alerts` and no alert traffic. */
export function canSeeAlerts(user) {
  return user?.role === 'admin' || user?.role === 'operator';
}
