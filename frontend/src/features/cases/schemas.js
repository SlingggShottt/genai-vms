import { z } from 'zod';

export const itemSchema = z.object({
  id: z.string(),
  kind: z.enum(['event', 'incident', 'footage', 'search', 'note']),
  ref: z.string().nullable(),
  label: z.string(),
  camera_id: z.string().nullable(),
  ts_start: z.string().nullable(),
  ts_end: z.string().nullable(),
  note: z.string().nullable(),
  created_at: z.string(),
});

export const caseSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().nullable(),
  status: z.enum(['open', 'closed']),
  item_count: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const casesSchema = z.array(caseSchema);
export const caseDetailSchema = caseSchema.extend({ items: z.array(itemSchema) });
