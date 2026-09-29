import { z } from 'zod';

export const cameraSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  rtsp_url: z.string(),
  site_id: z.string(),
  location_label: z.string().nullable(),
  lat: z.number().nullable(),
  lon: z.number().nullable(),
  enabled: z.boolean(),
  created_at: z.string(),
});

export const camerasPageSchema = z.object({
  items: z.array(cameraSchema),
  next_cursor: z.string().nullable(),
});

export const cameraStatusSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  status: z.enum(['online', 'reconnecting', 'offline']),
});

export const camerasStatusResponseSchema = z.object({
  cameras: z.array(cameraStatusSchema),
});

export const cameraFormSchema = z.object({
  code: z.string().min(1, 'Required').max(50),
  name: z.string().min(1, 'Required').max(200),
  rtsp_url: z.string().regex(/^rtsp:\/\/\S+$/, 'Must be a valid rtsp:// URL'),
  site_id: z.string().min(1, 'Required').max(100),
  location_label: z.string().max(200).optional(),
  enabled: z.boolean(),
});
