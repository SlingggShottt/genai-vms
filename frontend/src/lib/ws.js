/** The live channel: `WS /api/v1/ws?token=<access token>` (services/api/api/ws.py).
 *
 * Server -> client only. The server accepts the socket and then closes it with an application
 * code a browser can read:
 *   4401  token missing/invalid/expired -> mint a new access token, reconnect;
 *   1013  this client fell too far behind -> reconnect (the caller refetches what it missed).
 * Anything else (network drop, server restart) reconnects with backoff.
 *
 * A push is a hint, not the record: pub/sub keeps nothing, so every (re)connect after the first
 * is reported as `reconnect: true` and the owner refetches instead of trusting it missed nothing.
 */
import { refreshAccessToken } from './apiClient';
import { getAccessToken } from './tokenStore';

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_TOO_SLOW = 1013;
export const BACKOFF_MS = [1000, 2000, 5000, 10000, 30000];

const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

/** `ws(s)://<host>/api/v1/ws?token=…` for a relative or absolute API base. */
export function wsUrl(token, { base = BASE_URL, location = window.location } = {}) {
  const query = `token=${encodeURIComponent(token)}`;
  if (/^https?:\/\//.test(base)) {
    return `${base.replace(/^http/, 'ws').replace(/\/$/, '')}/ws?${query}`;
  }
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${location.host}${base.replace(/\/$/, '')}/ws?${query}`;
}

/**
 * @param {object} options
 * @param {(message: unknown) => void} options.onMessage  parsed JSON of every text frame
 * @param {(status: 'connecting'|'live'|'reconnecting'|'offline'|'closed') => void} [options.onStatus]
 * @param {(info: {reconnect: boolean}) => void} [options.onOpen]
 * @param {() => string|null} [options.getToken]
 * @param {() => Promise<unknown>} [options.refreshToken]
 */
export function createLiveSocket({
  onMessage,
  onStatus = () => {},
  onOpen = () => {},
  getToken = getAccessToken,
  refreshToken = refreshAccessToken,
  WebSocketImpl = globalThis.WebSocket,
  backoffMs = BACKOFF_MS,
  urlFor = wsUrl,
}) {
  let socket = null;
  let stopped = false;
  let everOpened = false;
  let attempt = 0;
  let timer = null;
  // Bumped by start() and stop(): an async step that began under an older generation (a token
  // refresh in flight when React StrictMode re-ran the effect) must not go on to open a socket.
  let generation = 0;

  function setStatus(status) {
    if (!stopped || status === 'closed') onStatus(status);
  }

  function schedule(delayMs) {
    clearTimeout(timer);
    timer = setTimeout(connect, delayMs);
  }

  async function connect() {
    if (stopped) return;
    const gen = generation;
    setStatus(everOpened ? 'reconnecting' : 'connecting');
    let token = getToken();
    if (!token) {
      try {
        await refreshToken();
      } catch {
        setStatus('offline'); // the session itself is gone; the router sends the user to /login
        return;
      }
      token = getToken();
      if (stopped || gen !== generation) return;
    }
    const current = new WebSocketImpl(urlFor(token));
    socket = current;

    current.onopen = () => {
      if (socket !== current || stopped) return;
      const reconnect = everOpened;
      everOpened = true;
      attempt = 0;
      setStatus('live');
      onOpen({ reconnect });
    };
    current.onmessage = (event) => {
      if (socket !== current || stopped) return;
      let parsed;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return; // not ours to interpret
      }
      onMessage(parsed);
    };
    current.onerror = () => {}; // `onclose` always follows and carries the code
    current.onclose = (event) => {
      if (socket !== current || stopped) return;
      socket = null;
      handleClose(event.code);
    };
  }

  async function handleClose(code) {
    const gen = generation;
    if (code === CLOSE_UNAUTHENTICATED) {
      setStatus('reconnecting');
      try {
        await refreshToken();
      } catch {
        setStatus('offline');
        return;
      }
      if (stopped || gen !== generation) return;
    }
    const delay = backoffMs[Math.min(attempt, backoffMs.length - 1)];
    attempt += 1;
    setStatus('reconnecting');
    // A normal expiry (4401 -> fresh token) or a drop-behind (1013) should not wait long, but
    // a server that keeps closing us must not be hammered: the first retry is immediate only
    // after a clean 4401 refresh, every later one backs off.
    schedule(code === CLOSE_UNAUTHENTICATED && attempt === 1 ? 0 : delay);
  }

  return {
    start() {
      generation += 1;
      stopped = false;
      // One tick later, not now: React StrictMode (dev) runs an effect, cleans it up and runs it
      // again straight away, and a socket opened and closed in that instant is an error in the
      // console. Deferred, the first run's stop() cancels it before anything is opened.
      schedule(0);
    },
    stop() {
      generation += 1;
      stopped = true;
      clearTimeout(timer);
      const current = socket;
      socket = null;
      if (current) {
        try {
          current.close(1000);
        } catch {
          // already closing
        }
      }
      onStatus('closed');
    },
  };
}
