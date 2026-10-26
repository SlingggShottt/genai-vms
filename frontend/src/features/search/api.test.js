import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '@/lib/apiClient';
import { getFrameNear, runCropSearch } from './api';

vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

const RESPONSE = {
  search_id: 's-1',
  query: 'part of a frame',
  mode: 'fast',
  kind: 'image',
  profile: 'local',
  results: [],
  timings_ms: { total: 10 },
  notes: [],
};

describe('runCropSearch', () => {
  beforeEach(() => {
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.get).mockReset();
  });

  it('names the frame by what the browser knows, never by a storage address', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(RESPONSE);

    await runCropSearch({
      frame: { search_id: 's-0', result_id: 'r-9' },
      bbox: [0.1, 0.2, 0.5, 0.9],
      cameras: ['cam02'],
      topK: 5,
    });

    expect(apiClient.post).toHaveBeenCalledWith('/search/image/crop', {
      search_id: 's-0',
      result_id: 'r-9',
      bbox: [0.1, 0.2, 0.5, 0.9],
      cameras: ['cam02'],
      top_k: 5,
    });
  });

  it('refuses an answer that is not a search response', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ results: 'none' });
    await expect(runCropSearch({ frame: {}, bbox: [0, 0, 1, 1] })).rejects.toThrow();
  });
});

describe('getFrameNear', () => {
  it('asks for the camera and the moment, and returns the picture and when it was taken', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      url: 'http://s3/near.jpg',
      at: '2026-10-25T09:30:19+00:00',
      camera_id: 'cam02',
    });

    const frame = await getFrameNear({ cameraId: 'cam02', at: '2026-10-25T09:30:15.000Z' });

    expect(vi.mocked(apiClient.get).mock.calls[0][0]).toBe(
      '/search/frame?camera_id=cam02&at=2026-10-25T09%3A30%3A15.000Z',
    );
    expect(frame).toEqual({
      url: 'http://s3/near.jpg',
      at: '2026-10-25T09:30:19+00:00',
      camera_id: 'cam02',
    });
  });
});
