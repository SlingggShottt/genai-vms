/** Keeping the TanStack Query caches in step with what the api and the live channel say.
 *
 * One alert reaches us three ways — a list fetch, the response to our own acknowledge/resolve,
 * and a WebSocket push — and they differ: a push carries no presigned keyframe urls (they are
 * made per request and never go over a shared channel). So an update is *merged* into what is
 * cached (`mergeAlert`), never allowed to wipe urls we already hold.
 */
import { alertSchema, wsEnvelopeSchema } from './schemas';
import { ALERTS_KEY, LIST_KEY, TRAY_KEY, alertKey } from './queries';

/** @returns the alert with `incoming`'s data and, if `incoming` has no urls, `existing`'s. */
export function mergeAlert(existing, incoming) {
  if (!existing) return incoming;
  return {
    ...incoming,
    keyframe_urls: incoming.keyframe_urls.length ? incoming.keyframe_urls : existing.keyframe_urls,
  };
}

/** Newest first. Alert ids are UUIDv7, so id order is creation order — the api sorts by it too. */
export function newestFirst(items) {
  return [...items].sort((a, b) => (a.id < b.id ? 1 : a.id > b.id ? -1 : 0));
}

/** The tray page after `alert` changed. A resolved alert leaves it; anything else is merged in
 * place or added. Returns the same object when nothing changed (no needless re-render).
 */
export function applyAlertToTray(page, alert) {
  if (!page) return page;
  const rest = page.items.filter((item) => item.id !== alert.id);
  const existing = page.items.find((item) => item.id === alert.id);
  if (alert.status === 'resolved') {
    return existing ? { ...page, items: rest } : page;
  }
  return { ...page, items: newestFirst([...rest, mergeAlert(existing, alert)]) };
}

/** An infinite list (`useInfiniteQuery` data) with `alert` replaced wherever it appears. */
export function applyAlertToList(data, alert) {
  if (!data?.pages) return data;
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => (item.id === alert.id ? mergeAlert(item, alert) : item)),
    })),
  };
}

/** Put a changed alert into every cache that may hold it, then refetch the lists it may now
 * belong to or have left (a filter on status or severity decides that, server side).
 */
export function applyAlert(queryClient, alert) {
  const tray = queryClient.getQueryData(TRAY_KEY);
  const known = tray?.items.some((item) => item.id === alert.id);
  queryClient.setQueryData(TRAY_KEY, (page) => applyAlertToTray(page, alert));
  if (tray && !known && alert.status !== 'resolved') {
    // Added from the payload, which is enough to show it; the refetch below corrects the order
    // and the 50-item window if this was an older alert changing than the page covers.
    queryClient.invalidateQueries({ queryKey: TRAY_KEY });
  }
  queryClient.setQueryData(alertKey(alert.id), (existing) =>
    existing ? mergeAlert(existing, alert) : undefined,
  );
  queryClient.setQueriesData({ queryKey: LIST_KEY }, (data) => applyAlertToList(data, alert));
  queryClient.invalidateQueries({ queryKey: LIST_KEY });
}

/**
 * Apply one raw WebSocket message. Unknown message types (`camera.status`, `job.progress`,
 * `incident.ready`: not ours yet) are ignored; a malformed alert payload is not trusted, the
 * alerts are refetched instead.
 * @returns {{kind: 'created'|'updated'|'ignored', alert?: object}}
 */
export function handleLiveMessage(queryClient, raw) {
  const envelope = wsEnvelopeSchema.safeParse(raw);
  if (!envelope.success) return { kind: 'ignored' };
  const { type, data } = envelope.data;
  if (type !== 'alert.created' && type !== 'alert.updated') return { kind: 'ignored' };

  const alert = alertSchema.safeParse(data);
  if (!alert.success) {
    queryClient.invalidateQueries({ queryKey: ALERTS_KEY });
    return { kind: 'ignored' };
  }
  applyAlert(queryClient, alert.data);
  return { kind: type === 'alert.created' ? 'created' : 'updated', alert: alert.data };
}

/** What a screen reader hears for a new alert (§B.10: polite, assertive only for critical). */
export function announcementFor(alert) {
  if (alert.severity === 'critical') {
    return { level: 'assertive', text: `Critical alert: ${alert.title}` };
  }
  return { level: 'polite', text: `New ${alert.severity} alert: ${alert.title}` };
}

/** Only a new high or critical alert pulses (§B.2: calm by default, loud on purpose). */
export function shouldPulse(alert) {
  return alert.severity === 'high' || alert.severity === 'critical';
}
