import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TimelineScrubber } from './TimelineScrubber';

const START = new Date('2026-10-01T07:04:00Z');
const END = new Date('2026-10-01T07:06:00Z');
const BUCKETS = [
  { start_ts: '2026-10-01T07:04:00Z', end_ts: '2026-10-01T07:05:00Z', count: 22 },
  { start_ts: '2026-10-01T07:05:00Z', end_ts: '2026-10-01T07:06:00Z', count: 19 },
];

function renderBars(buckets = BUCKETS) {
  const { container } = render(
    <TimelineScrubber
      buckets={buckets}
      rangeStart={START}
      rangeEnd={END}
      playheadMs={START.getTime()}
      onScrub={() => {}}
    />,
  );
  return [...container.querySelectorAll('[role="slider"] > div[aria-hidden="true"] > div')];
}

describe('TimelineScrubber density sparkline', () => {
  it('draws one bar per bucket, scaled to the busiest bucket', () => {
    const bars = renderBars();

    expect(bars).toHaveLength(2);
    expect(bars[0].style.height).toBe('100%');
    expect(parseFloat(bars[1].style.height)).toBeCloseTo((19 / 22) * 100, 1);
  });

  // Regression: the theme colours are plain `var(--…)` tokens, so Tailwind
  // can't derive an alpha from them and `bg-text-muted/40` emits no CSS — the
  // bars were laid out correctly but fully transparent (invisible sparkline).
  it('gives the bars a real background colour and dims them with the opacity utility', () => {
    const bars = renderBars();

    for (const bar of bars) {
      expect(bar).toHaveClass('bg-text-muted', 'opacity-40');
      expect(bar.className).not.toMatch(/bg-text-muted\/\d+/);
    }
  });

  it('draws no bars when there is no density data', () => {
    const bars = renderBars([]);

    expect(bars).toHaveLength(0);
  });
});
