import { z } from 'zod';

export const densityBucketSchema = z.object({
  start_ts: z.string(),
  end_ts: z.string(),
  count: z.number(),
});

export const densityResponseSchema = z.object({
  camera_id: z.string(),
  start: z.string(),
  end: z.string(),
  bucket_seconds: z.number(),
  buckets: z.array(densityBucketSchema),
});

export const overlayObjectSchema = z.object({
  track_id: z.string(),
  category: z.string(),
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]),
});

export const overlayFrameSchema = z.object({
  ts: z.string(),
  objects: z.array(overlayObjectSchema),
});

export const twinFramesResponseSchema = z.object({
  camera_id: z.string(),
  start: z.string(),
  end: z.string(),
  frames: z.array(overlayFrameSchema),
});

export const trackSummarySchema = z.object({
  track_id: z.string(),
  camera_id: z.string(),
  category: z.string(),
  first_ts: z.string(),
  last_ts: z.string(),
  dwell_s: z.number(),
  zones_visited: z.array(z.string()),
  attributes_summary: z.record(z.string(), z.string()),
});
