import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '@/lib/apiClient';
import { clearTokens, setTokens } from '@/lib/tokenStore';
import { hlsAuthConfig, isPresignedUrl, useTwinFrames } from './api';

vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn() } };
});

// Same shape services/api puts in the generated playlist: a SigV4
// query-string presigned MinIO URL.
const PRESIGNED_SEGMENT =
  'http://localhost:9000/vms-segments/cam01/2026/10/01/06/cam01_20261001T063437Z_000000.ts' +
  '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=vms-admin%2F20261001%2Fus-east-1%2Fs3%2Faws4_request' +
  '&X-Amz-Date=20261001T063500Z&X-Amz-Expires=900&X-Amz-SignedHeaders=host&X-Amz-Signature=abc123';

const MANIFEST_RELATIVE =
  '/api/v1/recordings/cam01/playlist.m3u8?start=2026-10-01T06%3A34%3A00.000Z&end=2026-10-01T06%3A35%3A00.000Z';
const MANIFEST_ABSOLUTE = `http://localhost:8000${MANIFEST_RELATIVE}`;

function fakeXhr() {
  return { setRequestHeader: vi.fn() };
}

describe('isPresignedUrl', () => {
  it('detects a SigV4 presigned segment URL', () => {
    expect(isPresignedUrl(PRESIGNED_SEGMENT)).toBe(true);
  });

  it('is false for the API manifest URL, relative or absolute', () => {
    expect(isPresignedUrl(MANIFEST_RELATIVE)).toBe(false);
    expect(isPresignedUrl(MANIFEST_ABSOLUTE)).toBe(false);
  });

  it('is false for a URL that merely mentions the parameter name outside the query', () => {
    expect(isPresignedUrl('http://localhost:9000/X-Amz-Signature=/seg.ts')).toBe(false);
  });
});

describe('hlsAuthConfig().xhrSetup', () => {
  beforeEach(() => {
    clearTokens();
  });

  it('attaches the bearer token to the manifest request', () => {
    setTokens({ accessToken: 'jwt-123' });
    const xhr = fakeXhr();

    hlsAuthConfig().xhrSetup(xhr, MANIFEST_ABSOLUTE);

    expect(xhr.setRequestHeader).toHaveBeenCalledWith('Authorization', 'Bearer jwt-123');
  });

  // Regression: S3/MinIO answers 400 "multiple authentication types" when a
  // presigned URL also carries an Authorization header, which broke every
  // playback with hls.js's "Playback failed" banner.
  it('does not send Authorization on presigned segment requests', () => {
    setTokens({ accessToken: 'jwt-123' });
    const xhr = fakeXhr();

    hlsAuthConfig().xhrSetup(xhr, PRESIGNED_SEGMENT);

    expect(xhr.setRequestHeader).not.toHaveBeenCalled();
  });

  it('sends nothing when there is no access token', () => {
    const xhr = fakeXhr();

    hlsAuthConfig().xhrSetup(xhr, MANIFEST_ABSOLUTE);

    expect(xhr.setRequestHeader).not.toHaveBeenCalled();
  });
});

function twinFramesResponse(startIso, trackId) {
  return {
    camera_id: 'cam01',
    start: startIso,
    end: startIso,
    frames: [
      {
        ts: startIso,
        objects: [{ track_id: trackId, category: 'person', bbox: [0.1, 0.2, 0.3, 0.4] }],
      },
    ],
  };
}

describe('useTwinFrames', () => {
  const WINDOW_1 = ['2026-10-01T07:04:00.000Z', '2026-10-01T07:05:00.000Z'];
  const WINDOW_2 = ['2026-10-01T07:05:00.000Z', '2026-10-01T07:06:00.000Z'];

  function renderTwinFrames() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    return renderHook(({ window }) => useTwinFrames('cam01', window[0], window[1]), {
      wrapper,
      initialProps: { window: WINDOW_1 },
    });
  }

  // Regression: the window key changes every 60 s of playback. Without
  // `keepPreviousData` the hook returned no data for the length of the next
  // window's fetch, so the detection boxes blinked out once a minute.
  it('keeps the previous window while the next one is still loading', async () => {
    let finishSecondWindow;
    apiClient.get
      .mockResolvedValueOnce(twinFramesResponse(WINDOW_1[0], 'cam01-t1'))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishSecondWindow = () => resolve(twinFramesResponse(WINDOW_2[0], 'cam01-t2'));
          }),
      );

    const { result, rerender } = renderTwinFrames();
    await waitFor(() =>
      expect(result.current.data?.frames[0].objects[0].track_id).toBe('cam01-t1'),
    );

    rerender({ window: WINDOW_2 });

    // Next window is in flight: the old boxes are still there, flagged as placeholder.
    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data?.frames[0].objects[0].track_id).toBe('cam01-t1');

    finishSecondWindow();
    await waitFor(() =>
      expect(result.current.data?.frames[0].objects[0].track_id).toBe('cam01-t2'),
    );
    expect(result.current.isPlaceholderData).toBe(false);
  });
});
