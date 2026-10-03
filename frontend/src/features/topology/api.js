import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { edgeSchema, edgesPageSchema } from './schemas';

export const EDGES_KEY = ['topology', 'edges'];

export function useEdges() {
  return useQuery({
    queryKey: EDGES_KEY,
    queryFn: async () => edgesPageSchema.parse(await apiClient.get('/topology/edges')).items,
  });
}

export function useCreateEdge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body) => edgeSchema.parse(await apiClient.post('/topology/edges', body)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: EDGES_KEY }),
  });
}

/** Only an edge's timing and direction can change; its cameras and type are its identity. */
export function useUpdateEdge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }) =>
      edgeSchema.parse(await apiClient.patch(`/topology/edges/${id}`, body)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: EDGES_KEY }),
  });
}

export function useDeleteEdge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      await apiClient.delete(`/topology/edges/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: EDGES_KEY }),
  });
}
