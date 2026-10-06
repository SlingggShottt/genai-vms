import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { caseDetailSchema, caseSchema, casesSchema, itemSchema } from './schemas';

export const CASES_KEY = ['cases'];

export function useCases({ enabled = true } = {}) {
  return useQuery({
    queryKey: CASES_KEY,
    queryFn: async () => casesSchema.parse(await apiClient.get('/cases')),
    enabled,
  });
}

export function useCase(id) {
  return useQuery({
    queryKey: [...CASES_KEY, id],
    queryFn: async () => caseDetailSchema.parse(await apiClient.get(`/cases/${id}`)),
    enabled: Boolean(id),
  });
}

export function useCreateCase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body) => caseSchema.parse(await apiClient.post('/cases', body)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CASES_KEY }),
  });
}

export function useUpdateCase(id) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body) => caseSchema.parse(await apiClient.patch(`/cases/${id}`, body)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CASES_KEY }),
  });
}

export function useDeleteCase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => apiClient.delete(`/cases/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CASES_KEY }),
  });
}

export function useAddItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ caseId, item }) =>
      itemSchema.parse(await apiClient.post(`/cases/${caseId}/items`, item)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CASES_KEY }),
  });
}

export function useRemoveItem(caseId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId) => apiClient.delete(`/cases/${caseId}/items/${itemId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CASES_KEY }),
  });
}
