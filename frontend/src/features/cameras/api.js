import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { camerasPageSchema, camerasStatusResponseSchema, cameraSchema } from './schemas';

export const CAMERAS_QUERY_KEY = ['cameras'];
export const CAMERA_STATUS_QUERY_KEY = ['cameras', 'status'];

export function useCameras() {
  return useQuery({
    queryKey: CAMERAS_QUERY_KEY,
    queryFn: async () => {
      const data = await apiClient.get('/cameras?limit=200');
      return camerasPageSchema.parse(data);
    },
  });
}

/** Polls every 5s per docs/style_guide.md §P1-J5 AC (VideoTile status dot
 * source) — the live wall and the settings page both use this.
 */
export function useCameraStatuses() {
  return useQuery({
    queryKey: CAMERA_STATUS_QUERY_KEY,
    queryFn: async () => {
      const data = await apiClient.get('/cameras/status');
      return camerasStatusResponseSchema.parse(data);
    },
    refetchInterval: 5000,
  });
}

export function useCreateCamera() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body) => {
      const data = await apiClient.post('/cameras', body);
      return cameraSchema.parse(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CAMERAS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: CAMERA_STATUS_QUERY_KEY });
    },
  });
}

export function useUpdateCamera() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }) => {
      const data = await apiClient.patch(`/cameras/${id}`, body);
      return cameraSchema.parse(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CAMERAS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: CAMERA_STATUS_QUERY_KEY });
    },
  });
}
