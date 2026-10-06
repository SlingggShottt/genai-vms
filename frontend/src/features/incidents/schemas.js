import { z } from 'zod';

export const jobSchema = z.object({
  id: z.string(),
  trigger: z.string(),
  status: z.enum(['queued', 'running', 'done', 'failed']),
  stage: z.string(),
  progress: z.number(),
  error: z.string().nullable(),
  incident_id: z.string().nullable(),
  group_id: z.string().nullable(),
  queue_position: z.number().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});

export const incidentSummarySchema = z.object({
  id: z.string(),
  title: z.string(),
  summary: z.string().nullable(),
  severity: z.enum(['low', 'medium', 'high', 'critical']),
  event_type: z.string(),
  status: z.enum(['generating', 'generated', 'failed', 'reviewed', 'closed']),
  camera_ids: z.array(z.string()),
  event_ids: z.array(z.string()),
  group_id: z.string().nullable(),
  window_start: z.string(),
  window_end: z.string(),
  confidence: z.number().nullable(),
  created_at: z.string(),
});

export const incidentsPageSchema = z.object({ items: z.array(incidentSummarySchema) });

const cited = { evidence: z.array(z.string()).default([]) };

const evidenceFrameSchema = z.object({
  id: z.string(),
  ts: z.string(),
  url: z.string().nullable().optional(),
});
const evidenceViewSchema = z.object({
  camera_id: z.string(),
  caption: z.object({ id: z.string(), text: z.string() }),
  vqa: z.array(z.object({ id: z.string(), q: z.string(), a: z.string() })).default([]),
  frames: z.array(evidenceFrameSchema).default([]),
});

export const evidenceSchema = z
  .object({
    phase_timeline: z.array(
      z.object({ phase: z.string(), start: z.string(), end: z.string(), source: z.string() }),
    ),
    phases: z.array(z.object({ phase: z.string(), views: z.array(evidenceViewSchema) })),
    events: z
      .array(
        z.object({
          id: z.string(),
          camera_id: z.string(),
          event_type: z.string(),
          caption: z.string().nullable().optional(),
        }),
      )
      .default([]),
    provenance: z.record(z.unknown()).default({}),
  })
  .passthrough();

const factorSchema = z.object({ text: z.string(), ...cited });

export const reportSchema = z
  .object({
    title: z.string(),
    summary: z.string().default(''),
    event_type: z.string(),
    severity: z.string(),
    cameras: z.array(z.string()),
    scene_understanding: z.object({
      location: z.string(),
      conditions: z.string(),
      actors: z.array(z.object({ ref: z.string(), description: z.string(), ...cited })),
    }),
    phase_analysis: z.array(z.object({ phase: z.string(), summary: z.string(), ...cited })),
    causal_chain: z.array(z.object({ step: z.number(), description: z.string(), ...cited })),
    contributing_factors: z.object({
      primary: z.array(factorSchema),
      environmental: z.array(factorSchema),
      security_gaps: z.array(factorSchema),
    }),
    recommended_actions: z.array(
      z.object({ action: z.string(), priority: z.string(), owner_role: z.string() }),
    ),
    confidence: z.number(),
    limitations: z.array(z.string()).default([]),
    provenance: z.record(z.unknown()).default({}),
  })
  .passthrough();

export const incidentDetailSchema = incidentSummarySchema.extend({
  report: reportSchema.nullable(),
  evidence: evidenceSchema.nullable(),
  provenance: z.record(z.unknown()),
  notes: z.string().nullable(),
  failure: z.string().nullable(),
});

export const reasoningStateSchema = z.object({
  job: jobSchema.nullable(),
  incident: incidentSummarySchema.nullable(),
});

export const similarSchema = z.object({
  items: z.array(
    z.object({
      incident_id: z.string(),
      title: z.string(),
      severity: z.string().nullable(),
      event_type: z.string().nullable(),
      camera_ids: z.array(z.string()),
      ts_start: z.number().nullable(),
      score: z.number(),
    }),
  ),
});
