import { useMutation } from '@tanstack/react-query';
import { z } from 'zod';
import { apiClient } from '@/lib/apiClient';
import { searchResponseSchema } from './schemas';

/** @param {{query: string, mode: 'fast'|'reason', cameras?: string[], start?: string, end?: string}} args */
export async function runSearch({ query, mode, cameras = [], start, end, jit = false }) {
  const body = {
    query,
    mode,
    jit: mode === 'reason' && jit,
    filters: { cameras, start: start ?? null, end: end ?? null },
  };
  return searchResponseSchema.parse(await apiClient.post('/search', body));
}

export async function runImageSearch({ file, cameras = [] }) {
  const form = new FormData();
  form.append('file', file);
  form.append('cameras', cameras.join(','));
  return searchResponseSchema.parse(await apiClient.post('/search/image', form));
}

export function useImageSearch() {
  return useMutation({ mutationFn: runImageSearch });
}

/** "Find similar" on a box drawn over a frame (P4-J1). `frame` names the frame the way the
 * browser knows it, never as a storage uri: `{event_id, keyframe_index}`, `{search_id,
 * result_id}` or `{camera_id, at}`. `bbox` is `[x0, y0, x1, y1]` as fractions of the frame.
 *
 * @param {{frame: object, bbox: number[], cameras?: string[], topK?: number}} args
 */
export async function runCropSearch({ frame, bbox, cameras = [], topK = 12 }) {
  const body = { ...frame, bbox, cameras, top_k: topK };
  return searchResponseSchema.parse(await apiClient.post('/search/image/crop', body));
}

const frameNearSchema = z.object({ url: z.string(), at: z.string(), camera_id: z.string() });

/** The stored frame nearest a moment of a camera, as a picture to draw a box on. `at` in the
 * answer is when that frame was taken: pass it back as the frame's `at`.
 *
 * @param {{cameraId: string, at: string}} args  `at` is an ISO time with a zone
 */
export async function getFrameNear({ cameraId, at }) {
  const query = new URLSearchParams({ camera_id: cameraId, at });
  return frameNearSchema.parse(await apiClient.get(`/search/frame?${query}`));
}
