import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useCurrentUser } from '@/features/auth/api';
import { createLiveSocket } from '@/lib/ws';
import { announcementFor, handleLiveMessage, shouldPulse } from './liveCache';
import { ALERTS_KEY, CORRELATIONS_KEY } from './queries';
import { canSeeAlerts } from './schemas';

/** How long an alert counts as "just arrived" (long enough for the 600 ms pulse). */
export const FRESH_MS = 1500;

const IDLE = { status: 'closed', polite: null, assertive: null, freshIds: new Set() };
const LiveAlertsContext = createContext(IDLE);

/** What the live channel is doing: `status` (connecting|live|reconnecting|offline|closed), the
 * latest screen-reader announcements and the ids of alerts that just arrived.
 */
export function useLiveAlerts() {
  return useContext(LiveAlertsContext);
}

/** One WebSocket per tab, for operators and admins (a viewer gets no alert traffic). Mounted
 * once in the app shell so the tray and the Events page share it.
 */
export function LiveAlertsProvider({ children }) {
  const { data: user } = useCurrentUser();
  const enabled = canSeeAlerts(user);
  const queryClient = useQueryClient();

  const [status, setStatus] = useState('closed');
  const [polite, setPolite] = useState(null);
  const [assertive, setAssertive] = useState(null);
  const [freshIds, setFreshIds] = useState(() => new Set());
  const sequence = useRef(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const timers = new Set();

    function markFresh(id) {
      setFreshIds((ids) => new Set(ids).add(id));
      const timer = setTimeout(() => {
        timers.delete(timer);
        setFreshIds((ids) => {
          const next = new Set(ids);
          next.delete(id);
          return next;
        });
      }, FRESH_MS);
      timers.add(timer);
    }

    const socket = createLiveSocket({
      onStatus: setStatus,
      onOpen: ({ reconnect }) => {
        // Pub/sub keeps nothing: after a gap, ask the api what we missed.
        if (reconnect) {
          queryClient.invalidateQueries({ queryKey: ALERTS_KEY });
          queryClient.invalidateQueries({ queryKey: CORRELATIONS_KEY });
        }
      },
      onMessage: (raw) => {
        const { kind, alert } = handleLiveMessage(queryClient, raw);
        if (kind !== 'created') return;
        const { level, text } = announcementFor(alert);
        sequence.current += 1;
        const message = { text, sequence: sequence.current };
        if (level === 'assertive') setAssertive(message);
        else setPolite(message);
        if (shouldPulse(alert)) markFresh(alert.id);
      },
    });
    socket.start();
    return () => {
      socket.stop();
      timers.forEach(clearTimeout);
    };
  }, [enabled, queryClient]);

  const value = useMemo(
    () => ({ status: enabled ? status : 'closed', polite, assertive, freshIds }),
    [enabled, status, polite, assertive, freshIds],
  );
  return <LiveAlertsContext.Provider value={value}>{children}</LiveAlertsContext.Provider>;
}
