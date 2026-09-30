import { useQuery } from '@tanstack/react-query';
import { apiClient, apiUrl } from '@/lib/apiClient';
import { getAccessToken } from '@/lib/tokenStore';
import { densityResponseSchema } from './schemas';

export const DENSITY_BUCKET_SECONDS = 60;

/** Density sparkline data for the timeline scrubber (FR-PLAY-02) —
 * `services/api`'s `/recordings/{camera}/density`, one point per minute
 * over the selected range.
 */
export function useRecordingDensity(cameraCode, startIso, endIso) {
  return useQuery({
    queryKey: ['recordings', 'density', cameraCode, startIso, endIso],
    queryFn: async () => {
      const params = new URLSearchParams({
        start: startIso,
        end: endIso,
        bucket: String(DENSITY_BUCKET_SECONDS),
      });
      const data = await apiClient.get(`/recordings/${cameraCode}/density?${params.toString()}`);
      return densityResponseSchema.parse(data);
    },
    enabled: Boolean(cameraCode && startIso && endIso),
  });
}

/** The raw playlist URL — hls.js loads this directly (its own XHR/fetch
 * loader, not `apiClient`), so it needs the request's own auth header via
 * `hlsAuthConfig()` below rather than going through `apiClient`.
 */
export function playlistUrl(cameraCode, startIso, endIso) {
  const params = new URLSearchParams({ start: startIso, end: endIso });
  return apiUrl(`/recordings/${cameraCode}/playlist.m3u8?${params.toString()}`);
}

/** hls.js config fragment that attaches the bearer token to every request
 * it makes (the manifest; segment URIs are presigned S3 links and need no
 * auth of their own). Spread into `new Hls({ ...hlsAuthConfig() })`.
 */
export function hlsAuthConfig() {
  return {
    xhrSetup: (xhr) => {
      const token = getAccessToken();
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    },
  };
}
