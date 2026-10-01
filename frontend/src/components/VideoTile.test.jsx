import { act, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { connectWhep } from '@/lib/mediamtx';
import { VideoTile } from './VideoTile';

const { hlsInstances } = vi.hoisted(() => ({ hlsInstances: [] }));

vi.mock('hls.js', () => {
  class Hls {
    static isSupported = vi.fn(() => true);
    static Events = { ERROR: 'hlsError', MANIFEST_PARSED: 'hlsManifestParsed' };
    constructor() {
      this.on = vi.fn();
      this.loadSource = vi.fn();
      this.attachMedia = vi.fn();
      this.destroy = vi.fn();
      hlsInstances.push(this);
    }
  }
  return { default: Hls };
});

vi.mock('@/lib/mediamtx', () => ({
  connectWhep: vi.fn(),
  hlsUrl: (code) => `http://mediamtx/${code}/index.m3u8`,
}));

const CAMERA = { code: 'cam01', name: 'Demo camera', status: 'online' };
const FIRST_FRAME_TIMEOUT_MS = 5000;

beforeEach(() => {
  vi.useFakeTimers();
  hlsInstances.length = 0;
  connectWhep.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

// Resolves the pending connectWhep() promise chain inside the component.
async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function renderTile() {
  const closeWhep = vi.fn();
  connectWhep.mockResolvedValue(closeWhep);
  const view = render(<VideoTile camera={CAMERA} />);
  await flushPromises();
  return { ...view, closeWhep, video: view.container.querySelector('video') };
}

// Regression: MediaMTX closes the WebRTC session of an H.264 stream with
// B-frames right after it negotiated, so connectWhep() resolves and the tile
// used to sit on a black, frameless WebRTC video forever.
describe('VideoTile WebRTC → HLS fallback', () => {
  it('falls back to HLS when WebRTC delivers no first frame in time', async () => {
    const { closeWhep, video } = await renderTile();
    video.srcObject = { fake: 'media stream' };
    expect(hlsInstances).toHaveLength(0);

    act(() => {
      vi.advanceTimersByTime(FIRST_FRAME_TIMEOUT_MS);
    });

    expect(closeWhep).toHaveBeenCalledTimes(1);
    expect(hlsInstances).toHaveLength(1);
    expect(hlsInstances[0].loadSource).toHaveBeenCalledWith('http://mediamtx/cam01/index.m3u8');
    expect(hlsInstances[0].attachMedia).toHaveBeenCalledWith(video);
    // A media element plays srcObject in preference to src, so it must be cleared.
    expect(video.srcObject).toBeNull();
  });

  it('stays on WebRTC when the first frame arrives in time', async () => {
    const { closeWhep, video } = await renderTile();

    act(() => {
      vi.advanceTimersByTime(FIRST_FRAME_TIMEOUT_MS - 1000);
    });
    fireEvent.loadedData(video);
    act(() => {
      vi.advanceTimersByTime(FIRST_FRAME_TIMEOUT_MS * 3);
    });

    expect(closeWhep).not.toHaveBeenCalled();
    expect(hlsInstances).toHaveLength(0);
  });

  it('does not arm the timeout when a frame is already showing', async () => {
    const closeWhep = vi.fn();
    connectWhep.mockImplementation(async (videoEl) => {
      Object.defineProperty(videoEl, 'readyState', { value: 4, configurable: true });
      return closeWhep;
    });
    render(<VideoTile camera={CAMERA} />);
    await flushPromises();

    act(() => {
      vi.advanceTimersByTime(FIRST_FRAME_TIMEOUT_MS * 3);
    });

    expect(closeWhep).not.toHaveBeenCalled();
    expect(hlsInstances).toHaveLength(0);
  });

  it('falls back to HLS when the WebRTC connection is lost after connecting', async () => {
    const { closeWhep, video } = await renderTile();
    const { onConnectionLost } = connectWhep.mock.calls[0][2];
    fireEvent.loadedData(video); // it was playing fine…

    act(() => {
      onConnectionLost(); // …then the connection failed
    });

    expect(closeWhep).toHaveBeenCalledTimes(1);
    expect(hlsInstances).toHaveLength(1);
  });

  it('falls back to HLS when the WHEP exchange is rejected (existing behaviour)', async () => {
    connectWhep.mockRejectedValue(new Error('WHEP offer rejected (404)'));
    render(<VideoTile camera={CAMERA} />);
    await flushPromises();

    expect(hlsInstances).toHaveLength(1);
  });

  it('falls back only once however many signals arrive', async () => {
    const { closeWhep } = await renderTile();
    const { onConnectionLost } = connectWhep.mock.calls[0][2];

    act(() => {
      onConnectionLost();
      onConnectionLost();
      vi.advanceTimersByTime(FIRST_FRAME_TIMEOUT_MS * 2);
    });

    expect(closeWhep).toHaveBeenCalledTimes(1);
    expect(hlsInstances).toHaveLength(1);
  });

  it('cleans up on unmount: no late fallback, session and HLS released', async () => {
    const { closeWhep, unmount } = await renderTile();

    unmount();
    act(() => {
      vi.advanceTimersByTime(FIRST_FRAME_TIMEOUT_MS * 2);
    });

    expect(closeWhep).toHaveBeenCalledTimes(1); // by the effect cleanup, not a fallback
    expect(hlsInstances).toHaveLength(0);
  });
});
