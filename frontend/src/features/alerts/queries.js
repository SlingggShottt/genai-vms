/** Query keys and the request builder for `/alerts` (services/api/api/alerts.py). Pure. */
export const ALERTS_KEY = ['alerts'];
export const TRAY_KEY = ['alerts', 'tray'];
export const LIST_KEY = ['alerts', 'list'];
export const alertKey = (id) => ['alerts', 'detail', id];
export const listKey = (filters) => ['alerts', 'list', filters];
export const CORRELATIONS_KEY = ['correlations'];
export const groupKey = (id) => ['correlations', id];

export const PAGE_SIZE = 50;

/** `?status=open&status=acknowledged&camera_id=cam02…` — lists repeat the parameter, empty
 * values are left out. `start`/`end` are ISO strings (the api filters on the event's start).
 */
export function alertsQueryString({
  status = [],
  severity = [],
  camera_id,
  group_id,
  start,
  end,
  limit = PAGE_SIZE,
  cursor,
} = {}) {
  const params = new URLSearchParams();
  for (const s of status) params.append('status', s);
  for (const s of severity) params.append('severity', s);
  if (camera_id) params.set('camera_id', camera_id);
  if (group_id) params.set('group_id', group_id);
  if (start) params.set('start', start);
  if (end) params.set('end', end);
  params.set('limit', String(limit));
  if (cursor) params.set('cursor', cursor);
  return `?${params.toString()}`;
}

/** What the tray shows: everything still waiting for a person. */
export const TRAY_FILTERS = { status: ['open', 'acknowledged'] };
