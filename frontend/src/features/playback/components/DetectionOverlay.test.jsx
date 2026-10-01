import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DetectionOverlay } from './DetectionOverlay';

// jsdom has no layout, ResizeObserver, canvas context or animation frames —
// stub just enough for the component to mount.
beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal('requestAnimationFrame', () => 1);
  vi.stubGlobal('cancelAnimationFrame', () => {});
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ clearRect: vi.fn() });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderCanvas(enabled) {
  const { container } = render(
    <DetectionOverlay
      videoRef={{ current: document.createElement('video') }}
      fragmentsRef={{ current: [] }}
      frames={[]}
      enabled={enabled}
      onSelectTrack={() => {}}
    />,
  );
  return container.querySelector('canvas');
}

// Regression: a <canvas> is a replaced element, so `inset-*` alone doesn't
// stretch it. Without an explicit width/height it stayed at the intrinsic
// 300x150 and every detection box was drawn bunched into the top-left corner.
describe('DetectionOverlay canvas sizing', () => {
  it('has an explicit width and height when overlays are on', () => {
    const canvas = renderCanvas(true);

    expect(canvas).toHaveClass('w-full');
    expect(canvas.className).toMatch(/\bh-\[calc\(100%-2\.5rem\)\]/);
    expect(canvas).toHaveClass('cursor-pointer');
    expect(canvas).not.toHaveClass('pointer-events-none');
  });

  it('has an explicit width and height when overlays are off, and is click-through', () => {
    const canvas = renderCanvas(false);

    expect(canvas).toHaveClass('w-full', 'h-full', 'pointer-events-none');
  });
});
