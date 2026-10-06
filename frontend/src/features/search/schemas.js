import { z } from 'zod';

/** @typedef {z.infer<typeof searchResponseSchema>} SearchResponse */

export const searchResultSchema = z.object({
  result_id: z.string(),
  camera_id: z.string(),
  segment_ids: z.array(z.string()),
  start_ts: z.string(),
  end_ts: z.string(),
  score: z.number(),
  fused_score: z.number(),
  reasoning_score: z.number().nullable().optional(),
  trace: z.string().nullable().optional(),
  missing: z.array(z.string()).default([]),
  jit_answers: z
    .array(
      z.object({
        question: z.string(),
        answer: z.enum(['yes', 'no', 'unsure']),
        detail: z.string().default(''),
        cached: z.boolean().default(false),
      }),
    )
    .default([]),
  keyframe_url: z.string().nullable().optional(),
  crop_urls: z.array(z.string()).default([]),
  matched_track_ids: z.array(z.string()).default([]),
  categories: z.array(z.string()).default([]),
  colors: z.array(z.string()).default([]),
  zones: z.array(z.string()).default([]),
  event_ids: z.array(z.string()).default([]),
  incident_ids: z.array(z.string()).default([]),
  caption: z.string().nullable().optional(),
  sources: z.array(z.string()).default([]),
});

const planSchema = z
  .object({
    entities: z.array(z.object({ category: z.string(), attributes: z.record(z.string()) })),
    spatial: z.object({ zones: z.array(z.string()), cameras: z.array(z.string()) }),
    temporal: z.object({ start: z.string().nullable(), end: z.string().nullable() }),
    event_types_hint: z.array(z.string()),
    sub_questions: z.array(z.string()),
    source: z.string(),
  })
  .passthrough();

export const searchResponseSchema = z.object({
  search_id: z.string(),
  query: z.string(),
  mode: z.enum(['fast', 'reason']),
  kind: z.enum(['text', 'image']).default('text'),
  profile: z.string(),
  plan: planSchema.nullable().optional(),
  results: z.array(searchResultSchema),
  timings_ms: z.record(z.number()).default({}),
  notes: z.array(z.string()).default([]),
});
