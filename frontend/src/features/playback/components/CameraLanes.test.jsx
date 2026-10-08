import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CameraLanes } from './CameraLanes';

const T0 = Date.parse('2026-10-06T12:00:00.000Z');
const SPANS = [
  { phase: 'baseline', startMs: T0, endMs: T0 + 10_000 },
  { phase: 'action', startMs: T0 + 10_000, endMs: T0 + 40_000 },
];

function lanes(props = {}) {
  return render(
    <CameraLanes
      lanes={[
        { key: 'a', label: 'Waiting room' },
        { key: 'b', label: 'Car park' },
      ]}
      spans={SPANS}
      rangeStartMs={T0}
      rangeEndMs={T0 + 40_000}
      playheadMs={T0 + 10_000}
      {...props}
    />,
  );
}

describe('CameraLanes', () => {
  it('draws one lane per camera, each with the phases', () => {
    lanes();
    expect(screen.getByText('Waiting room')).toBeTruthy();
    expect(screen.getByText('Car park')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /Baseline/ })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /Action/ })).toHaveLength(2);
  });

  it('places the phases and the playhead by their share of the range', () => {
    const { container } = lanes();
    const action = screen.getAllByRole('button', { name: /Action/ })[0];
    expect(action.style.left).toBe('25%');
    expect(action.style.width).toBe('calc(75%)');
    const playhead = container.querySelector('[aria-hidden="true"]');
    expect(playhead.style.left).toBe('25%');
  });

  it('selects a phase when it is pressed, without moving the playhead', () => {
    const onSelectPhase = vi.fn();
    const onScrub = vi.fn();
    lanes({ onSelectPhase, onScrub });
    fireEvent.click(screen.getAllByRole('button', { name: /Action/ })[1]);
    expect(onSelectPhase).toHaveBeenCalledWith('action');
    expect(onScrub).not.toHaveBeenCalled();
  });

  it('moves the playhead to where a lane is pressed', () => {
    const onScrub = vi.fn();
    const { container } = lanes({ onScrub });
    const lane = container.querySelector('.cursor-pointer');
    lane.getBoundingClientRect = () => ({ left: 100, width: 400, top: 0, height: 28 });
    fireEvent.click(lane, { clientX: 300 }); // halfway along the lane
    expect(onScrub).toHaveBeenCalledWith(T0 + 20_000);
    fireEvent.click(lane, { clientX: 9999 }); // beyond the end stays at the end
    expect(onScrub).toHaveBeenLastCalledWith(T0 + 40_000);
  });
});
