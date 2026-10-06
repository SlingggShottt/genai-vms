import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { reportDetailSchema, reportSummarySchema, reportsSchema } from './schemas';

export const REPORTS_KEY = ['reports', 'daily'];

const live = (r) => r.status === 'queued' || r.status === 'generating';

export function useReports() {
  return useQuery({
    queryKey: REPORTS_KEY,
    queryFn: async () => reportsSchema.parse(await apiClient.get('/reports/daily')),
    refetchInterval: (query) => (query.state.data?.some(live) ? 3000 : false),
  });
}

export function useReport(id) {
  return useQuery({
    queryKey: [...REPORTS_KEY, id],
    queryFn: async () => reportDetailSchema.parse(await apiClient.get(`/reports/daily/${id}`)),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data && live(query.state.data) ? 3000 : false),
  });
}

export function useRequestReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (range) =>
      reportSummarySchema.parse(await apiClient.post('/reports/daily', range)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: REPORTS_KEY }),
  });
}
