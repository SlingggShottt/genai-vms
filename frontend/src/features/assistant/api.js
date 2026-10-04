import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { sessionDetailSchema, sessionSchema, sessionsSchema, startersSchema } from './schemas';

export const SESSIONS_KEY = ['assistant', 'sessions'];
export const sessionKey = (id) => ['assistant', 'session', id];

export function useSessions() {
  return useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: async () => sessionsSchema.parse(await apiClient.get('/assistant/sessions')),
  });
}

export function useSession(id) {
  return useQuery({
    queryKey: sessionKey(id),
    queryFn: async () =>
      sessionDetailSchema.parse(await apiClient.get(`/assistant/sessions/${id}`)),
    enabled: Boolean(id),
  });
}

export function useStarters() {
  return useQuery({
    queryKey: ['assistant', 'starters'],
    queryFn: async () => startersSchema.parse(await apiClient.get('/assistant/starters')),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => sessionSchema.parse(await apiClient.post('/assistant/sessions', {})),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SESSIONS_KEY }),
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => apiClient.delete(`/assistant/sessions/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SESSIONS_KEY }),
  });
}

/** The alert page that shows an event, or null if the event raised no alert. */
export async function alertForEvent(eventId) {
  const data = await apiClient.get(`/events/${eventId}/alert`);
  return data?.alert_id ?? null;
}
