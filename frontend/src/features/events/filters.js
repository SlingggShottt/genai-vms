/** The Events page's filters. They live in the URL (`?status=open&severity=high&camera=cam02`)
 * so a view can be shared and the back button works; this turns that into the api's query and
 * back. Pure.
 */
import { ALERT_STATUSES, SEVERITIES } from '@/features/alerts/schemas';

/** @typedef {{status: string, severity: string, camera: string, from: string, to: string}} Filters
 * All strings; '' means "any". `from`/`to` are `datetime-local` values (the browser's local time,
 * like the Playback page).
 */
export const EMPTY_FILTERS = { status: '', severity: '', camera: '', from: '', to: '' };

/** @returns {Filters} what the URL says; anything not a known value is treated as "any". */
export function filtersFromSearch(searchParams) {
  const pick = (name, allowed) => {
    const value = searchParams.get(name) ?? '';
    return allowed ? (allowed.includes(value) ? value : '') : value;
  };
  return {
    status: pick('status', ALERT_STATUSES),
    severity: pick('severity', SEVERITIES),
    camera: pick('camera'),
    from: pick('from'),
    to: pick('to'),
  };
}

/** @returns {URLSearchParams} only the filters that are set. */
export function searchFromFilters(filters) {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) {
    if (value) params.set(name, value);
  }
  return params;
}

export function hasFilters(filters) {
  return Object.values(filters).some(Boolean);
}

/** `datetime-local` text -> a Date, or null if it is blank or not a date. */
export function parseLocal(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** @returns {string|null} what is wrong with the time range, in words an operator can act on. */
export function rangeError({ from, to }) {
  const start = parseLocal(from);
  const end = parseLocal(to);
  if (from && !start) return 'Start is not a valid date and time.';
  if (to && !end) return 'End is not a valid date and time.';
  if (start && end && end <= start) return 'End must be after start.';
  return null;
}

/**
 * The argument of `useAlertsList` / `alertsQueryString` for these filters. A range that is
 * invalid is left out rather than sent (the api would answer 400): the form shows the reason.
 */
export function apiFilters(filters) {
  const valid = !rangeError(filters);
  const start = valid ? parseLocal(filters.from) : null;
  const end = valid ? parseLocal(filters.to) : null;
  return {
    status: filters.status ? [filters.status] : [],
    severity: filters.severity ? [filters.severity] : [],
    camera_id: filters.camera || undefined,
    start: start ? start.toISOString() : undefined,
    end: end ? end.toISOString() : undefined,
  };
}
