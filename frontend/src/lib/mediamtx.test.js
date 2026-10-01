import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { connectWhep } from './mediamtx';

// jsdom has no WebRTC — fake just the surface connectWhep uses.
let peerConnections;

class FakeMediaStream {}

class FakePeerConnection {
  constructor() {
    this.connectionState = 'new';
    this.closed = false;
    peerConnections.push(this);
  }
  addTransceiver() {}
  async createOffer() {
    return { type: 'offer', sdp: 'offer-sdp' };
  }
  async setLocalDescription() {}
  async setRemoteDescription() {}
  close() {
    this.closed = true;
  }
  // What the browser does when the connection changes state on its own.
  browserSetsState(state) {
    this.connectionState = state;
    this.onconnectionstatechange?.();
  }
}

beforeEach(() => {
  peerConnections = [];
  vi.stubGlobal('RTCPeerConnection', FakePeerConnection);
  vi.stubGlobal('MediaStream', FakeMediaStream);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url, init) =>
      init?.method === 'DELETE'
        ? { ok: true }
        : {
            ok: true,
            status: 201,
            text: async () => 'answer-sdp',
            headers: { get: () => '/cam01/whep/session-1' },
          },
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function fakeVideo() {
  return { srcObject: null };
}

describe('connectWhep onConnectionLost', () => {
  // Regression: MediaMTX closes the session of an H.264 stream with B-frames
  // (WebRTC can't carry them) right after it negotiated, and the browser only
  // reports the connection `failed` ~15 s later. The tile never noticed and
  // stayed black; the caller needs a signal to fall back to HLS.
  it('reports a connection that fails on its own, once', async () => {
    const onConnectionLost = vi.fn();
    await connectWhep(fakeVideo(), 'cam01', { onConnectionLost });

    peerConnections[0].browserSetsState('failed');
    peerConnections[0].browserSetsState('closed');

    expect(onConnectionLost).toHaveBeenCalledTimes(1);
  });

  it('also reports a connection the remote end closed', async () => {
    const onConnectionLost = vi.fn();
    await connectWhep(fakeVideo(), 'cam01', { onConnectionLost });

    peerConnections[0].browserSetsState('closed');

    expect(onConnectionLost).toHaveBeenCalledTimes(1);
  });

  it('ignores transient states that can still recover', async () => {
    const onConnectionLost = vi.fn();
    await connectWhep(fakeVideo(), 'cam01', { onConnectionLost });

    peerConnections[0].browserSetsState('connecting');
    peerConnections[0].browserSetsState('connected');
    peerConnections[0].browserSetsState('disconnected');

    expect(onConnectionLost).not.toHaveBeenCalled();
  });

  it('stays quiet after the caller closed the session itself', async () => {
    const onConnectionLost = vi.fn();
    const close = await connectWhep(fakeVideo(), 'cam01', { onConnectionLost });

    close();
    peerConnections[0].browserSetsState('closed');

    expect(onConnectionLost).not.toHaveBeenCalled();
  });

  it('works without a callback', async () => {
    await connectWhep(fakeVideo(), 'cam01');

    expect(() => peerConnections[0].browserSetsState('failed')).not.toThrow();
  });
});

describe('connectWhep close()', () => {
  it('releases the video element and the server-side session', async () => {
    const video = fakeVideo();
    const close = await connectWhep(video, 'cam01');
    expect(video.srcObject).toBeInstanceOf(FakeMediaStream);

    close();

    expect(video.srcObject).toBeNull();
    expect(peerConnections[0].closed).toBe(true);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/cam01/whep/session-1'), {
      method: 'DELETE',
    });
  });

  // After a fallback to HLS the caller has already cleared `srcObject` and
  // attached hls.js; a late close() must not reset whatever is playing now.
  it('does not touch srcObject once it is no longer its own stream', async () => {
    const video = fakeVideo();
    const close = await connectWhep(video, 'cam01');
    const somethingElse = {};
    video.srcObject = somethingElse;

    close();

    expect(video.srcObject).toBe(somethingElse);
  });
});
