import { eventTypeLabel } from '@/lib/eventTypes';

/** Seconds of footage shown before and after an event, for context. */
export const CLIP_PADDING_S = 10;

/** The recording range to play for an event: its window, padded on both sides. */
export function clipRange(alert, paddingS = CLIP_PADDING_S) {
  const start = new Date(new Date(alert.start_ts).getTime() - paddingS * 1000);
  const end = new Date(new Date(alert.end_ts).getTime() + paddingS * 1000);
  return { startIso: start.toISOString(), endIso: end.toISOString() };
}

/** Below this the model itself was unsure: say so plainly (§B.8). */
export const LOW_CONFIDENCE = 0.5;

/** @returns {{text: string, low: boolean}} how the VLM check went, for the event detail. */
export function verificationNote(alert) {
  if (alert.verification_status !== 'verified') {
    return { text: 'Not checked by the vision model.', low: false };
  }
  if (alert.confidence == null) return { text: 'Verified by the vision model.', low: false };
  const percent = Math.round(alert.confidence * 100);
  return {
    text: `Verified by the vision model, ${percent}% confidence.`,
    low: alert.confidence < LOW_CONFIDENCE,
  };
}

/**
 * Why two correlated events were linked, in words. `delta_s` is, for a transit link, the start of
 * the later event minus the end of the earlier one; for an overlap link, the gap between the two
 * windows (0 when they intersect).
 * @param {{from_event: string, to_event: string, edge_type: string, delta_s: number, score: number}} link
 * @param {Map<string, {camera_id: string, event_type: string}>} byEvent
 */
export function describeLink(link, byEvent) {
  const from = byEvent.get(link.from_event);
  const to = byEvent.get(link.to_event);
  const fromName = from ? `${eventTypeLabel(from.event_type)} on ${from.camera_id}` : 'An event';
  const toName = to ? `${eventTypeLabel(to.event_type)} on ${to.camera_id}` : 'an event';
  const score = link.score.toFixed(2);
  if (link.edge_type === 'transit') {
    const seconds = Math.round(link.delta_s);
    return `${fromName}, then ${toName} ${seconds} s later (camera path, score ${score})`;
  }
  const overlap = link.delta_s <= 0 ? 'at the same time' : `${Math.round(link.delta_s)} s apart`;
  return `${fromName} and ${toName}, ${overlap} (overlapping views, score ${score})`;
}
