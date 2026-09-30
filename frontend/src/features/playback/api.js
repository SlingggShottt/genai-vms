import { useQuery } from '@tanstack/react-query';
import { apiClient, apiUrl } from '@/lib/apiClient';
import { getAccessToken } from '@/lib/tokenStore';
import { densityResponseSchema, trackSummarySchema, twinFramesResponseSchema } from './schemas';

export const DENSITY_BUCKET_SECONDS = 60;

// Matches services/api's MAX_WINDOW_SECONDS on /twin/{camera}/frames
// (api/api/twin.py) — a whole twin document is fetched from S3 per
// matched segment, so the window is kept short and re-fetched as the
// playhead advances rather than loaded once for the whole range.
export const OVERLAY_WINDOW_SECONDS = 60;

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

/** Overlay-ready bboxes for one <= 60s window (P2-J6, FR-PLAY-03) —
 * `services/api`'s `/twin/{camera}/frames`. `windowStartIso`/`windowEndIso`
 * should be aligned to `OVERLAY_WINDOW_SECONDS` boundaries of the active
 * playback range so the query cache naturally dedups as the playhead
 * moves within one window instead of refetching every tick.
 */
export function useTwinFrames(cameraCode, windowStartIso, windowEndIso) {
  return useQuery({
    queryKey: ['twin', 'frames', cameraCode, windowStartIso, windowEndIso],
    queryFn: async () => {
      const params = new URLSearchParams({ start: windowStartIso, end: windowEndIso });
      const data = await apiClient.get(`/twin/${cameraCode}/frames?${params.toString()}`);
      return twinFramesResponseSchema.parse(data);
    },
    enabled: Boolean(cameraCode && windowStartIso && windowEndIso),
    staleTime: Infinity, // recorded footage is immutable once indexed
  });
}

/** Side-panel data for a clicked overlay box — `services/api`'s
 * `/tracks/{track_id}`.
 */
export function useTrackSummary(trackId) {
  return useQuery({
    queryKey: ['tracks', trackId],
    queryFn: async () => {
      const data = await apiClient.get(`/tracks/${trackId}`);
      return trackSummarySchema.parse(data);
    },
    enabled: Boolean(trackId),
    staleTime: Infinity,
  });
}
