import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SyncedPlayer } from './SyncedPlayer';

// hls.js is replaced by a fake that hands each <video> its playlist (the fragments a camera
// recorded) and never plays anything: the test drives `currentTime`, `readyState` and `paused`.
const { hlsInstances, playlists } = vi.hoisted(() => ({ hlsInstances: [], playlists: {} }));

vi.mock('hls.js', () => {
  class Hls {
    static isSupported = vi.fn(() => true);
    static Events = { ERROR: 'hlsError', LEVEL_LOADED: 'hlsLevelLoaded' };
    constructor() {
      this.handlers = {};
      this.on = (name, fn) => {
        this.handlers[name] = fn;
      };
      this.loadSource = (url) => {
        this.url = url;
      };
      this.attachMedia = (video) => {
        this.video = video;
        const camera = new URL(this.url, 'http://x').pathname.split('/')[4];
        let currentTime = 0;
        let paused = true;
        Object.defineProperties(video, {
          currentTime: {
            get: () => currentTime,
            set: (v) => {
              currentTime = v;
            },
            configurable: true,
          },
          paused: { get: () => paused, configurable: true },
          readyState: { get: () => video.fakeReadyState ?? 4, configurable: true },
        });
        video.fakeReadyState = 4;
        video.play = vi.fn(() => {
          paused = false;
          return Promise.resolve();
        });
        video.pause = vi.fn(() => {
          paused = true;
        });
        this.handlers.hlsLevelLoaded?.('hlsLevelLoaded', {
          details: { fragments: playlists[camera] },
        });
      };
      this.destroy = vi.fn();
      hlsInstances.push(this);
    }
  }
  return { default: Hls };
});

vi.mock('../api', () => ({
  playlistUrl: (camera) => `/api/v1/recordings/${camera}/playlist.m3u8`,
  hlsAuthConfig: () => ({}),
}));

const T0 = Date.parse('2026-10-06T12:00:00.000Z');
const START = new Date(T0).toISOString();
const END = new Date(T0 + 40_000).toISOString();

// 40 s of footage, in four 10 s fragments
const full = (offsetMs = 0) =>
  [0, 1, 2, 3].map((i) => ({
    start: i * 10,
    duration: 10,
    programDateTime: T0 + offsetMs + i * 10_000,
  }));

const TIMELINE = [
  { phase: 'baseline', start: START, end: new Date(T0 + 10_000).toISOString() },
  {
    phase: 'action',
    start: new Date(T0 + 10_000).toISOString(),
    end: new Date(T0 + 20_000).toISOString(),
  },
];

const status = () => screen.getByTestId('sync-status');
const attr = (name) => Number(status().getAttribute(name));
const videos = () => [...document.querySelectorAll('video')];

// Time passes in 100 ms steps; a playing picture advances with it, as a healthy player does.
async function advance(ms) {
  for (let elapsed = 0; elapsed < ms; elapsed += 100) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    for (const v of videos()) {
      if (!v.paused && v.readyState >= 3) v.currentTime += 0.1 * (v.playbackRate || 1);
    }
  }
}

function setup(props = {}) {
  render(
    <SyncedPlayer
      views={[
        { camera: 'camA', label: 'Camera A' },
        { camera: 'camB', label: 'Camera B' },
      ]}
      startIso={START}
      endIso={END}
      timeline={TIMELINE}
      {...props}
    />,
  );
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'performance'],
  });
  hlsInstances.length = 0;
  playlists.camA = full();
  playlists.camB = full();
});

afterEach(() => {
  vi.useRealTimers();
});

// Lets the fake "player" follow the playhead the way a healthy one does: its time is the playhead.
function followPlayhead() {
  for (const v of videos()) v.currentTime = (attr('data-playhead-ms') - T0) / 1000;
}

describe('SyncedPlayer', () => {
  it('shows every camera and starts paused at the beginning of the range', async () => {
    setup();
    await advance(400);
    expect(screen.getAllByText('Camera A').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Camera B').length).toBeGreaterThan(0);
    expect(status().getAttribute('data-playing')).toBe('false');
    expect(attr('data-playhead-ms')).toBe(T0);
    expect(videos().every((v) => v.paused)).toBe(true);
  });

  it('plays all pictures together and moves the playhead with real time', async () => {
    setup();
    await advance(400);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(2000);
    expect(status().getAttribute('data-playing')).toBe('true');
    expect(videos().every((v) => !v.paused)).toBe(true);
    expect(attr('data-playhead-ms') - T0).toBeGreaterThan(1500);
    expect(attr('data-playhead-ms') - T0).toBeLessThan(2600);
  });

  it('pulls a picture that has drifted past 300 ms back to the playhead, and counts it', async () => {
    setup();
    await advance(400);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(2500); // past the settling time
    followPlayhead();
    const [, b] = videos();
    b.currentTime += 2; // camera B runs two seconds ahead
    const before = attr('data-corrections');
    await advance(400);
    expect(Math.abs(b.currentTime - (attr('data-playhead-ms') - T0) / 1000)).toBeLessThan(0.6);
    expect(attr('data-corrections')).toBe(before + 1);
    expect(attr('data-max-drift-ms')).toBeGreaterThan(300);
  });

  it('closes a small gap by running that picture slower, not by jumping', async () => {
    setup();
    await advance(400);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(2500);
    const [a, b] = videos();
    b.currentTime += 0.2; // two tenths of a second ahead
    const corrections = attr('data-corrections');
    await advance(200);
    expect(b.playbackRate).toBeLessThan(1);
    expect(a.playbackRate).toBe(1);
    await advance(6000); // it drifts back into step at 5 % slower...
    expect(b.playbackRate).toBe(1); // ...and then goes back to normal speed
    expect(attr('data-corrections')).toBe(corrections); // no seek was needed
    expect(Math.abs(b.currentTime - (attr('data-playhead-ms') - T0) / 1000)).toBeLessThan(0.2);
  });

  it('leaves pictures that are within 300 ms alone', async () => {
    setup();
    await advance(400);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(2500);
    for (let i = 0; i < 5; i++) {
      followPlayhead();
      videos()[1].currentTime += 0.2;
      await advance(200);
    }
    expect(attr('data-corrections')).toBe(0);
    expect(attr('data-max-drift-ms')).toBeLessThanOrEqual(300);
  });

  it('says so, and pauses that camera, where it recorded nothing', async () => {
    playlists.camB = [{ start: 0, duration: 10, programDateTime: T0 + 20_000 }]; // from 20 s on
    setup();
    await advance(400);
    expect(screen.getByText('No recording at this time.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(1000);
    const [a, b] = videos();
    expect(a.paused).toBe(false);
    expect(b.paused).toBe(true); // it has nothing to show, the other camera plays on
    fireEvent.change(screen.getByRole('slider', { name: 'Position' }), {
      target: { value: String(T0 + 25_000) },
    });
    await advance(400);
    expect(screen.queryByText('No recording at this time.')).toBeNull();
  });

  it('pauses a camera that runs into a recording gap while the others play on', async () => {
    playlists.camB = [
      { start: 0, duration: 10, programDateTime: T0 },
      { start: 10, duration: 10, programDateTime: T0 + 20_000 },
    ]; // nothing from 10 s to 20 s
    setup();
    await advance(400);
    fireEvent.change(screen.getByRole('slider', { name: 'Position' }), {
      target: { value: String(T0 + 8_000) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(1000);
    const [a, b] = videos();
    expect(a.paused).toBe(false);
    expect(b.paused).toBe(false); // still inside its footage
    await advance(2000); // the playhead is now at about 11 s
    expect(a.paused).toBe(false);
    expect(b.paused).toBe(true);
    expect(screen.getByText('No recording at this time.')).toBeTruthy();
  });

  it('does not count a scrub as drift', async () => {
    setup();
    await advance(400);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(2500);
    fireEvent.change(screen.getByRole('slider', { name: 'Position' }), {
      target: { value: String(T0 + 30_000) },
    });
    await advance(1200);
    expect(attr('data-max-drift-ms')).toBeLessThanOrEqual(300);
    expect(attr('data-playhead-ms')).toBeGreaterThanOrEqual(T0 + 30_000);
  });

  it('holds the playhead while a camera that has footage is still buffering', async () => {
    setup();
    await advance(400);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await advance(1000);
    const [a, b] = videos();
    b.fakeReadyState = 1; // nothing to show yet
    const held = attr('data-playhead-ms');
    await advance(1500);
    expect(attr('data-playhead-ms')).toBe(held);
    expect(a.paused).toBe(true); // the others wait for it rather than running ahead
    b.fakeReadyState = 4;
    await advance(1000);
    expect(attr('data-playhead-ms')).toBeGreaterThan(held);
    expect(a.paused).toBe(false);
  });

  it('plays a phase from its start and stops at its end', async () => {
    setup();
    await advance(400);
    fireEvent.click(
      within(screen.getByRole('list', { name: 'Play a phase' })).getByRole('button', {
        name: /^Action/,
      }),
    );
    await advance(300);
    expect(attr('data-playhead-ms')).toBeGreaterThanOrEqual(T0 + 10_000);
    expect(status().getAttribute('data-playing')).toBe('true');
    await advance(11_000);
    expect(status().getAttribute('data-playing')).toBe('false');
    expect(attr('data-playhead-ms')).toBe(T0 + 20_000);
  });

  it('follows a phase chosen by the parent', async () => {
    const { rerender } = render(
      <SyncedPlayer
        views={[{ camera: 'camA', label: 'Camera A' }]}
        startIso={START}
        endIso={END}
        timeline={TIMELINE}
        activePhase={null}
      />,
    );
    await advance(400);
    rerender(
      <SyncedPlayer
        views={[{ camera: 'camA', label: 'Camera A' }]}
        startIso={START}
        endIso={END}
        timeline={TIMELINE}
        activePhase="action"
      />,
    );
    await advance(300);
    expect(status().getAttribute('data-playing')).toBe('true');
    expect(attr('data-playhead-ms')).toBeGreaterThanOrEqual(T0 + 10_000);
  });

  it('shows at most four cameras', async () => {
    for (const c of ['c1', 'c2', 'c3', 'c4', 'c5']) playlists[c] = full();
    render(
      <SyncedPlayer
        views={['c1', 'c2', 'c3', 'c4', 'c5'].map((camera) => ({ camera, label: camera }))}
        startIso={START}
        endIso={END}
      />,
    );
    await advance(400);
    expect(videos()).toHaveLength(4);
  });
});
