import { z } from 'zod';

export const reportSummarySchema = z.object({
  id: z.string(),
  date_from: z.string(),
  date_to: z.string(),
  status: z.enum(['queued', 'generating', 'ready', 'failed']),
  narrative_source: z.string().nullable(),
  error: z.string().nullable(),
  created_at: z.string(),
  finished_at: z.string().nullable(),
  has_pdf: z.boolean().default(false),
});

export const reportsSchema = z.array(reportSummarySchema);

export const factsSchema = z
  .object({
    date_from: z.string(),
    date_to: z.string(),
    events_total: z.number(),
    events_rejected: z.number(),
    by_type: z.record(z.number()),
    by_camera: z.record(z.number()),
    by_severity: z.record(z.number()),
    by_hour: z.record(z.number()),
    incidents_total: z.number(),
    incidents: z.array(
      z.object({
        id: z.string(),
        title: z.string(),
        severity: z.string(),
        event_type: z.string(),
        cameras: z.array(z.string()),
        at: z.string(),
      }),
    ),
    alerts_total: z.number(),
    alerts_open: z.number(),
    ack_p50_s: z.number().nullable(),
    ack_p90_s: z.number().nullable(),
    resolve_p50_s: z.number().nullable(),
    resolve_p90_s: z.number().nullable(),
    people_peak_by_camera: z.record(z.number()),
    groups_total: z.number(),
    groups_multi_camera: z.number(),
  })
  .passthrough();

export const reportDetailSchema = reportSummarySchema.extend({
  narrative: z.string().nullable(),
  facts: factsSchema.nullable(),
});
