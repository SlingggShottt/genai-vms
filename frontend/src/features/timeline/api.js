import { useQuery } from '@tanstack/react-query';
import { z } from 'zod';
import { apiClient } from '@/lib/apiClient';

const timelineSchema = z.object({
  start: z.string(),
  end: z.string(),
  cameras: z.array(z.string()),
  events: z.array(
    z.object({
      id: z.string(),
      camera_id: z.string(),
      event_type: z.string(),
      severity: z.string(),
      start: z.string(),
      end: z.string(),
      caption: z.string().nullable(),
      alert_id: z.string().nullable(),
    }),
  ),
  incidents: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      severity: z.string(),
      event_type: z.string(),
      camera_ids: z.array(z.string()),
      start: z.string(),
      end: z.string(),
    }),
  ),
  groups: z.array(
    z.object({
      id: z.string(),
      camera_ids: z.array(z.string()),
      severity: z.string(),
      start: z.string(),
      end: z.string(),
      events: z.number(),
    }),
  ),
});

export function useTimeline(startIso, endIso) {
  return useQuery({
    queryKey: ['timeline', startIso, endIso],
    queryFn: async () => {
      const qs = new URLSearchParams({ start: startIso, end: endIso });
      return timelineSchema.parse(await apiClient.get(`/timeline?${qs.toString()}`));
    },
    placeholderData: (prev) => prev,
  });
}
