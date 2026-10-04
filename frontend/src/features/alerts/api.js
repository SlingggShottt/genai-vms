import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { applyAlert } from './liveCache';
import {
  PAGE_SIZE,
  TRAY_FILTERS,
  TRAY_KEY,
  alertKey,
  alertsQueryString,
  groupKey,
  listKey,
} from './queries';
import { alertSchema, alertsPageSchema, correlationGroupDetailSchema } from './schemas';

/** Open and acknowledged alerts, newest first — the tray. Operators and admins only: the api
 * answers 403 to a viewer, so callers pass `enabled`.
 */
export function useTrayAlerts({ enabled = true } = {}) {
  return useQuery({
    queryKey: TRAY_KEY,
    queryFn: async () => {
      const data = await apiClient.get(`/alerts${alertsQueryString(TRAY_FILTERS)}`);
      return alertsPageSchema.parse(data);
    },
    enabled,
  });
}

/** The Events page: filtered, cursor-paginated. `filters` is the shape `alertsQueryString` takes. */
export function useAlertsList(filters, { enabled = true } = {}) {
  return useInfiniteQuery({
    queryKey: listKey(filters),
    queryFn: async ({ pageParam }) => {
      const data = await apiClient.get(
        `/alerts${alertsQueryString({ ...filters, limit: PAGE_SIZE, cursor: pageParam })}`,
      );
      return alertsPageSchema.parse(data);
    },
    initialPageParam: undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** One alert with fresh presigned keyframe urls (they live 15 minutes: refetch on focus). */
export function useAlert(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: alertKey(id),
    queryFn: async () => alertSchema.parse(await apiClient.get(`/alerts/${id}`)),
    enabled: enabled && Boolean(id),
    staleTime: 5 * 60 * 1000, // well inside the 15-minute lifetime of the urls
  });
}

/** The correlation group of an alert: its member events and why they were linked. */
export function useCorrelationGroup(groupId) {
  return useQuery({
    queryKey: groupKey(groupId),
    queryFn: async () =>
      correlationGroupDetailSchema.parse(await apiClient.get(`/correlations/${groupId}`)),
    enabled: Boolean(groupId),
  });
}

const ACTION_PATH = { acknowledge: 'ack', resolve: 'resolve' };

/** Acknowledge or resolve. On success the new alert goes straight into every cache; a 409
 * (someone got there first) surfaces as an `ApiError` the dialog explains.
 */
export function useAlertAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, action, note }) => {
      const body = note?.trim() ? { note: note.trim() } : {};
      return alertSchema.parse(await apiClient.post(`/alerts/${id}/${ACTION_PATH[action]}`, body));
    },
    onSuccess: (alert) => applyAlert(queryClient, alert),
    onError: () => {
      // Whatever the reason (409: already handled; 404: gone), show what is true now.
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}
