import { useMutation } from '@tanstack/react-query';
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
