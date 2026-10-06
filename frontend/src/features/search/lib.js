/** Where "Open in playback" lands: the camera and a window around the result, so the clip
 * starts a few seconds before the match.
 */
export function playbackLink(result, padSeconds = 6) {
  const start = new Date(new Date(result.start_ts).getTime() - padSeconds * 1000);
  const end = new Date(new Date(result.end_ts).getTime() + padSeconds * 1000);
  const params = new URLSearchParams({
    camera: result.camera_id,
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return `/playback?${params.toString()}`;
}

export const TIME_RANGES = [
  { value: 'any', label: 'Any time', seconds: null },
  { value: '1h', label: 'Last hour', seconds: 3600 },
  { value: '6h', label: 'Last 6 hours', seconds: 6 * 3600 },
  { value: '24h', label: 'Last 24 hours', seconds: 24 * 3600 },
  { value: '7d', label: 'Last 7 days', seconds: 7 * 24 * 3600 },
];

export function rangeFilter(value, now = new Date()) {
  const range = TIME_RANGES.find((r) => r.value === value);
  if (!range || range.seconds == null) return {};
  return {
    start: new Date(now.getTime() - range.seconds * 1000).toISOString(),
    end: now.toISOString(),
  };
}

/** A one-line reading of how the query was understood, for the strip above the results. */
export function planSummary(plan) {
  if (!plan) return '';
  const bits = [];
  for (const e of plan.entities) {
    const color = e.attributes?.color;
    bits.push(color ? `${color} ${e.category}` : e.category);
  }
  if (plan.spatial.zones.length) bits.push(`in ${plan.spatial.zones.join(', ')}`);
  if (plan.temporal.start) bits.push('time range applied');
  if (plan.event_types_hint.length) {
    bits.push(plan.event_types_hint.map((t) => t.replace(/_/g, ' ')).join(' / '));
  }
  return bits.join(' · ');
}
