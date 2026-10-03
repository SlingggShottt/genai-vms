import { useEffect, useState } from 'react';

/** The current time, refreshed every `intervalMs`, so "2 min ago" keeps counting. One ticker
 * per list (pass `now` down) rather than one timer per row.
 */
export function useNow(intervalMs = 30000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
