import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import {
  incidentDetailSchema,
  incidentsPageSchema,
  incidentSummarySchema,
  jobSchema,
  reasoningStateSchema,
} from './schemas';

export const incidentsKey = ['incidents'];

export function useIncidents(filters = {}) {
  const params = new URLSearchParams();
  for (const s of filters.status ?? []) params.append('status', s);
  for (const s of filters.severity ?? []) params.append('severity', s);
  if (filters.camera) params.set('camera_id', filters.camera);
  const qs = params.toString();
  return useQuery({
    queryKey: [...incidentsKey, qs],
    queryFn: async () =>
      incidentsPageSchema.parse(await apiClient.get(`/incidents${qs ? `?${qs}` : ''}`)),
    // A report being written appears in the list as "generating": keep it fresh while any is.
    refetchInterval: (query) =>
      query.state.data?.items.some((i) => i.status === 'generating') ? 4000 : false,
  });
}

/** One incident. While its report is still being written it is refetched every few seconds. */
export function useIncident(id) {
  return useQuery({
    queryKey: [...incidentsKey, id],
    queryFn: async () => incidentDetailSchema.parse(await apiClient.get(`/incidents/${id}`)),
    enabled: Boolean(id),
    staleTime: 60 * 1000, // frame urls last 15 minutes
    refetchInterval: (query) => (query.state.data?.status === 'generating' ? 4000 : false),
  });
}

export function useUpdateIncident(id) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body) =>
      incidentSummarySchema.parse(await apiClient.patch(`/incidents/${id}`, body)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: incidentsKey }),
  });
}

/** Where an event's analysis stands: the queued/running job and the newest report. Polled
 * while a job is live. */
export function useEventReasoning(eventId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['event-reasoning', eventId],
    queryFn: async () =>
      reasoningStateSchema.parse(await apiClient.get(`/events/${eventId}/reasoning`)),
    enabled: enabled && Boolean(eventId),
    refetchInterval: (query) => {
      const status = query.state.data?.job?.status;
      return status === 'queued' || status === 'running' ? 3000 : false;
    },
  });
}

export function useAnalyzeEvent(eventId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => jobSchema.parse(await apiClient.post(`/events/${eventId}/analyze`, {})),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['event-reasoning', eventId] });
      queryClient.invalidateQueries({ queryKey: incidentsKey });
    },
  });
}
