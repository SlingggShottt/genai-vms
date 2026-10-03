import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { zoneSchema, zonesPageSchema } from './schemas';

export const zonesKey = (cameraId) => ['zones', cameraId];

/** The zones of one camera (by its `core.cameras.id`). Idle until a camera is chosen. */
export function useZones(cameraId) {
  return useQuery({
    queryKey: zonesKey(cameraId),
    enabled: Boolean(cameraId),
    queryFn: async () => {
      const data = await apiClient.get(`/cameras/${cameraId}/zones`);
      return zonesPageSchema.parse(data).items;
    },
  });
}

export function useCreateZone(cameraId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body) =>
      zoneSchema.parse(await apiClient.post(`/cameras/${cameraId}/zones`, body)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: zonesKey(cameraId) }),
  });
}

export function useUpdateZone(cameraId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }) =>
      zoneSchema.parse(await apiClient.patch(`/zones/${id}`, body)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: zonesKey(cameraId) }),
  });
}

export function useDeleteZone(cameraId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      await apiClient.delete(`/zones/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: zonesKey(cameraId) }),
  });
}
