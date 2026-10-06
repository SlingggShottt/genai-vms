export const PRESETS = [
  { value: '1h', label: 'Last hour', ms: 3600e3 },
  { value: '3h', label: 'Last 3 hours', ms: 3 * 3600e3 },
  { value: '6h', label: 'Last 6 hours', ms: 6 * 3600e3 },
  { value: '24h', label: 'Last 24 hours', ms: 24 * 3600e3 },
  { value: '7d', label: 'Last 7 days', ms: 7 * 24 * 3600e3 },
];

/** Position of an instant within [start, end] as a percentage, clamped to the lane. */
export function pct(ts, start, end) {
  const p = ((new Date(ts).getTime() - start) / (end - start)) * 100;
  return Math.min(100, Math.max(0, p));
}

/** A bar's left edge and width (percent); never thinner than `min` so a one-second event shows. */
export function span(from, to, start, end, min = 0.4) {
  const left = pct(from, start, end);
  const right = pct(to, start, end);
  return { left, width: Math.max(right - left, min) };
}

/** Pick a tick step that gives 4–10 labels across the range. */
export function tickStep(rangeMs) {
  const steps = [60e3, 5 * 60e3, 10 * 60e3, 30 * 60e3, 3600e3, 3 * 3600e3, 6 * 3600e3, 24 * 3600e3];
  return steps.find((s) => rangeMs / s <= 10) ?? steps.at(-1);
}

export function ticks(start, end) {
  const step = tickStep(end - start);
  const first = Math.ceil(start / step) * step;
  const out = [];
  for (let t = first; t < end; t += step) out.push(t);
  return out;
}

/** The selection a drag from `a` to `b` (fractions of the lane, 0–1) makes. */
export function selectionRange(a, b, start, end) {
  const [lo, hi] = a <= b ? [a, b] : [b, a];
  return { start: start + lo * (end - start), end: start + hi * (end - start) };
}
