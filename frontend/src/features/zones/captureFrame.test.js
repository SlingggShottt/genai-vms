import { describe, expect, it, vi } from 'vitest';
import { NoPictureError, captureFrame } from './captureFrame';

function fakeCanvas({ context, blob = new Blob(['jpeg'], { type: 'image/jpeg' }) } = {}) {
  const canvas = {
    width: 0,
    height: 0,
    getContext: vi.fn(() => context),
    toBlob: vi.fn((callback) => callback(blob)),
  };
  return canvas;
}

const playingVideo = { readyState: 4, videoWidth: 1280, videoHeight: 720 };

describe('captureFrame', () => {
  it('draws the video at its own resolution and returns the JPEG with its size', async () => {
    const context = { drawImage: vi.fn() };
    const canvas = fakeCanvas({ context });
    const result = await captureFrame(playingVideo, { createCanvas: () => canvas, quality: 0.7 });
    expect(canvas.width).toBe(1280);
    expect(canvas.height).toBe(720);
    expect(context.drawImage).toHaveBeenCalledWith(playingVideo, 0, 0, 1280, 720);
    expect(canvas.toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', 0.7);
    expect(result).toEqual({ blob: expect.any(Blob), width: 1280, height: 720 });
  });

  it('encodes at a quality of 0.85 unless told otherwise', async () => {
    const canvas = fakeCanvas({ context: { drawImage: vi.fn() } });
    await captureFrame(playingVideo, { createCanvas: () => canvas });
    expect(canvas.toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', 0.85);
  });

  it.each([
    ['no video element', null],
    ['a video with no data yet', { readyState: 1, videoWidth: 1280, videoHeight: 720 }],
    ['a video with no width', { readyState: 4, videoWidth: 0, videoHeight: 720 }],
    ['a video with no height', { readyState: 4, videoWidth: 1280, videoHeight: 0 }],
  ])('says there is no picture for %s, and never touches a canvas', async (_label, video) => {
    const createCanvas = vi.fn();
    await expect(captureFrame(video, { createCanvas })).rejects.toThrow(NoPictureError);
    await expect(captureFrame(video, { createCanvas })).rejects.toThrow(/No picture yet/);
    expect(createCanvas).not.toHaveBeenCalled();
  });

  it('accepts a video that has just reached "current data"', async () => {
    const canvas = fakeCanvas({ context: { drawImage: vi.fn() } });
    await expect(
      captureFrame({ ...playingVideo, readyState: 2 }, { createCanvas: () => canvas }),
    ).resolves.toMatchObject({ width: 1280 });
  });

  it('explains a browser with no 2D canvas', async () => {
    const canvas = fakeCanvas({ context: null });
    await expect(captureFrame(playingVideo, { createCanvas: () => canvas })).rejects.toThrow(
      /can't capture a frame/,
    );
  });

  it('explains a stream the page may not read back', async () => {
    const context = {
      drawImage: vi.fn(() => {
        throw new DOMException('tainted', 'SecurityError');
      }),
    };
    await expect(
      captureFrame(playingVideo, { createCanvas: () => fakeCanvas({ context }) }),
    ).rejects.toThrow(/CORS/);
  });

  it('explains an encoder that produced nothing', async () => {
    const canvas = fakeCanvas({ context: { drawImage: vi.fn() }, blob: null });
    await expect(captureFrame(playingVideo, { createCanvas: () => canvas })).rejects.toThrow(
      /Could not capture/,
    );
  });
});
