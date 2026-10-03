import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKOFF_MS, CLOSE_TOO_SLOW, CLOSE_UNAUTHENTICATED, createLiveSocket, wsUrl } from './ws';

class FakeWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.closedWith = null;
    FakeWebSocket.instances.push(this);
  }

  close(code) {
    this.closedWith = code;
  }

  // helpers the tests use to play the server
  open() {
    this.onopen?.();
  }

  send(data) {
    this.onmessage?.({ data });
  }

  drop(code) {
    this.onclose?.({ code });
  }
}

function setup(overrides = {}) {
  const statuses = [];
  const messages = [];
  const opens = [];
  let token = 'tok-1';
  const refreshToken = vi.fn(async () => {
    token = `tok-${refreshToken.mock.calls.length + 1}`;
  });
  const socket = createLiveSocket({
    onMessage: (m) => messages.push(m),
    onStatus: (s) => statuses.push(s),
    onOpen: (info) => opens.push(info),
    getToken: () => token,
    refreshToken,
    WebSocketImpl: FakeWebSocket,
    urlFor: (t) => `ws://test/ws?token=${t}`,
    ...overrides,
  });
  return {
    socket,
    statuses,
    messages,
    opens,
    refreshToken,
    setToken: (t) => {
      token = t;
    },
  };
}

const last = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1];

describe('wsUrl', () => {
  it('builds a ws:// url on the page host for the relative API base', () => {
    const location = { protocol: 'http:', host: 'localhost:5173' };
    expect(wsUrl('a b', { base: '/api/v1', location })).toBe(
      'ws://localhost:5173/api/v1/ws?token=a%20b',
    );
  });

  it('uses wss:// when the page is https', () => {
    const location = { protocol: 'https:', host: 'vms.example.com' };
    expect(wsUrl('t', { base: '/api/v1/', location })).toBe(
      'wss://vms.example.com/api/v1/ws?token=t',
    );
  });

  it('swaps the scheme of an absolute API base', () => {
    expect(wsUrl('t', { base: 'https://api.example.com/api/v1' })).toBe(
      'wss://api.example.com/api/v1/ws?token=t',
    );
    expect(wsUrl('t', { base: 'http://localhost:8000/api/v1' })).toBe(
      'ws://localhost:8000/api/v1/ws?token=t',
    );
  });

  it('percent-encodes the token', () => {
    expect(
      wsUrl('a&b=c', { base: '/api/v1', location: { protocol: 'http:', host: 'h' } }),
    ).toContain('token=a%26b%3Dc');
  });
});

describe('createLiveSocket', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('connects with the current token and reports connecting then live', async () => {
    const { socket, statuses, opens } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(last().url).toBe('ws://test/ws?token=tok-1');
    expect(statuses).toEqual(['connecting']);
    last().open();
    expect(statuses).toEqual(['connecting', 'live']);
    expect(opens).toEqual([{ reconnect: false }]);
  });

  it('delivers parsed messages and ignores frames that are not JSON', async () => {
    const { socket, messages } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();
    last().send(JSON.stringify({ type: 'alert.created', data: { id: 'a1' } }));
    last().send('not json at all');
    last().send(JSON.stringify({ type: 'camera.status', data: {} }));
    expect(messages.map((m) => m.type)).toEqual(['alert.created', 'camera.status']);
  });

  it('reconnects with the backoff steps after a network drop, then resets once connected', async () => {
    const { socket, statuses, opens } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();

    for (const delay of [BACKOFF_MS[0], BACKOFF_MS[1], BACKOFF_MS[2]]) {
      const before = FakeWebSocket.instances.length;
      last().drop(1006);
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(FakeWebSocket.instances.length).toBe(before); // not a moment early
      await vi.advanceTimersByTimeAsync(1);
      expect(FakeWebSocket.instances.length).toBe(before + 1);
    }

    last().open();
    expect(opens.at(-1)).toEqual({ reconnect: true }); // the owner refetches what it missed
    expect(statuses.at(-1)).toBe('live');

    // connected again: the next drop starts from the first step, not the fourth
    const before = FakeWebSocket.instances.length;
    last().drop(1006);
    await vi.advanceTimersByTimeAsync(BACKOFF_MS[0]);
    expect(FakeWebSocket.instances.length).toBe(before + 1);
  });

  it('settles at the last backoff step: it neither speeds up nor waits longer', async () => {
    const { socket } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    for (let i = 0; i < BACKOFF_MS.length + 3; i += 1) {
      last().drop(1006);
      await vi.advanceTimersByTimeAsync(BACKOFF_MS.at(-1));
    }
    const cap = BACKOFF_MS.at(-1);
    const before = FakeWebSocket.instances.length;
    last().drop(1006);
    await vi.advanceTimersByTimeAsync(cap - 1);
    expect(FakeWebSocket.instances.length).toBe(before); // not a tight reconnect loop
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeWebSocket.instances.length).toBe(before + 1); // and not longer than the cap
  });

  it('refreshes the token and reconnects at once on a 4401 close', async () => {
    const { socket, refreshToken, statuses } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();

    last().drop(CLOSE_UNAUTHENTICATED);
    await vi.advanceTimersByTimeAsync(0);

    expect(refreshToken).toHaveBeenCalledTimes(1);
    expect(last().url).toBe('ws://test/ws?token=tok-2'); // the new token, without waiting
    expect(statuses).toContain('reconnecting');
  });

  it('backs off when 4401 keeps coming back instead of refreshing in a tight loop', async () => {
    const { socket, refreshToken } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().drop(CLOSE_UNAUTHENTICATED); // first: refresh, reconnect at once
    await vi.advanceTimersByTimeAsync(0);
    const before = FakeWebSocket.instances.length;
    last().drop(CLOSE_UNAUTHENTICATED); // again without ever opening: wait
    await vi.advanceTimersByTimeAsync(BACKOFF_MS[1] - 1);
    expect(FakeWebSocket.instances.length).toBe(before);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeWebSocket.instances.length).toBe(before + 1);
    expect(refreshToken).toHaveBeenCalledTimes(2);
  });

  it('goes offline and stops when the session cannot be refreshed', async () => {
    const refreshToken = vi.fn().mockRejectedValue(new Error('session expired'));
    const { socket, statuses } = setup({ refreshToken });
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();
    const count = FakeWebSocket.instances.length;

    last().drop(CLOSE_UNAUTHENTICATED);
    await vi.advanceTimersByTimeAsync(BACKOFF_MS.at(-1) * 2);

    expect(statuses.at(-1)).toBe('offline');
    expect(FakeWebSocket.instances.length).toBe(count); // no reconnect attempts
  });

  it('reconnects after being dropped for falling behind (1013)', async () => {
    const { socket, opens } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();
    last().drop(CLOSE_TOO_SLOW);
    await vi.advanceTimersByTimeAsync(BACKOFF_MS[0]);
    last().open();
    expect(opens.at(-1)).toEqual({ reconnect: true });
  });

  it('fetches a token first when none is held yet', async () => {
    const { socket, setToken, refreshToken } = setup();
    setToken(null);
    refreshToken.mockImplementation(async () => setToken('fresh'));
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(refreshToken).toHaveBeenCalledTimes(1);
    expect(last().url).toBe('ws://test/ws?token=fresh');
  });

  it('goes offline when there is no token and none can be had', async () => {
    const { socket, setToken, statuses } = setup({
      refreshToken: vi.fn().mockRejectedValue(new Error('no session')),
    });
    setToken(null);
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(statuses.at(-1)).toBe('offline');
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it('stop() closes the socket, cancels a pending reconnect and never reconnects', async () => {
    const { socket, statuses } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();
    last().drop(1006); // a reconnect is now scheduled
    socket.stop();
    await vi.advanceTimersByTimeAsync(BACKOFF_MS.at(-1) * 2);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(statuses.at(-1)).toBe('closed');

    // and stopping a live socket closes it politely without a reconnect
    FakeWebSocket.instances = [];
    const second = setup();
    second.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    const open = last();
    open.open();
    second.socket.stop();
    expect(open.closedWith).toBe(1000);
    open.drop(1006); // late event from the dead socket
    await vi.advanceTimersByTimeAsync(BACKOFF_MS.at(-1) * 2);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('ignores messages and events from a socket it has replaced', async () => {
    const { socket, messages } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    const old = last();
    old.open();
    old.drop(1006);
    await vi.advanceTimersByTimeAsync(BACKOFF_MS[0]);
    last().open();
    old.send(JSON.stringify({ type: 'alert.created', data: {} }));
    old.drop(1006); // must not schedule another reconnect
    const count = FakeWebSocket.instances.length;
    await vi.advanceTimersByTimeAsync(BACKOFF_MS.at(-1) * 2);
    expect(messages).toEqual([]);
    expect(FakeWebSocket.instances).toHaveLength(count);
  });

  it('a stop straight after start (StrictMode) opens no socket at all', async () => {
    const { socket, statuses } = setup();
    socket.start();
    socket.stop(); // the cleanup of the effect's first run
    socket.start(); // and its second run
    await vi.advanceTimersByTimeAsync(0);
    expect(FakeWebSocket.instances).toHaveLength(1); // only the second run's socket was ever opened
    expect(statuses.filter((s) => s === 'connecting')).toHaveLength(1);
  });

  it('a stop/start pair while a token refresh is in flight opens one socket, not two', async () => {
    // What React StrictMode does to an effect: run, clean up, run again. Each run asks for a
    // token and both answers arrive later: only the current run may open a socket.
    const releases = [];
    const refreshToken = vi.fn(() => new Promise((resolve) => releases.push(resolve)));
    const { socket, setToken } = setup({ refreshToken });
    setToken(null);
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    socket.stop();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(releases).toHaveLength(2); // both runs are waiting for their token
    setToken('fresh');
    releases.forEach((release) => release());
    await vi.advanceTimersByTimeAsync(0);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('a 4401 refresh that finishes after stop/start does not open a second socket beside the new one', async () => {
    const releases = [];
    const refreshToken = vi.fn(() => new Promise((resolve) => releases.push(resolve)));
    const { socket } = setup({ refreshToken });
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();
    last().drop(CLOSE_UNAUTHENTICATED); // the old run is now waiting for a new token
    await vi.advanceTimersByTimeAsync(0);
    socket.stop();
    socket.start(); // the effect re-ran: a new run opens its own socket
    await vi.advanceTimersByTimeAsync(0);
    last().open();
    expect(FakeWebSocket.instances).toHaveLength(2);

    releases[0](); // the old run's refresh finally answers
    await vi.advanceTimersByTimeAsync(BACKOFF_MS.at(-1));

    expect(FakeWebSocket.instances).toHaveLength(2); // never a third, live beside the second
  });

  it('stop() leaves no reconnect timer pending', async () => {
    const { socket } = setup();
    socket.start();
    await vi.advanceTimersByTimeAsync(0);
    last().open();
    last().drop(1006); // schedules a reconnect
    expect(vi.getTimerCount()).toBe(1);
    socket.stop();
    expect(vi.getTimerCount()).toBe(0);
  });
});
