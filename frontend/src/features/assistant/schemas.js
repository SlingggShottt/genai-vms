import { z } from 'zod';

export const citationSchema = z.object({
  kind: z.enum(['E', 'I', 'S']),
  tag: z.string(),
  ref: z.string(),
  label: z.string(),
  ts: z.string().nullable().optional(),
  camera: z.string().nullable().optional(),
  consulted: z.boolean().optional(),
});

export const toolRunSchema = z.object({
  tool: z.string().nullable(),
  arguments: z.record(z.unknown()).default({}),
  summary: z.string().nullable().optional(),
  lines: z.array(z.string()).default([]),
  cites: z.array(citationSchema).default([]),
});

export const messageSchema = z.object({
  id: z.string(),
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  citations: z.array(citationSchema).default([]),
  tools: z.array(toolRunSchema).default([]),
  status: z.string().default('complete'),
  created_at: z.string(),
});

export const sessionSchema = z.object({
  id: z.string(),
  title: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const sessionsSchema = z.object({ items: z.array(sessionSchema) });
export const sessionDetailSchema = sessionSchema.extend({ messages: z.array(messageSchema) });
export const startersSchema = z.object({ questions: z.array(z.string()) });
