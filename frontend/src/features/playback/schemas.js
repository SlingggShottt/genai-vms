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
