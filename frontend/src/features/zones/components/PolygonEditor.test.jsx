import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_POINTS } from '../polygon';
import { PolygonEditor } from './PolygonEditor';

const TRIANGLE = [
  [0.2, 0.2],
  [0.8, 0.2],
  [0.5, 0.8],
];

// A 400 x 225 frame at the page origin.
const RECT = { left: 0, top: 0, width: 400, height: 225, right: 400, bottom: 225, x: 0, y: 0 };

/** The editor is controlled; this holds the state a page would, and reports every change. */
function Harness({ initial = [], onChangeSpy = () => {}, ...props }) {
  const [points, setPoints] = useState(initial);
  return (
    <PolygonEditor
      frameUrl="blob:frame"
      points={points}
      onChange={(next) => {
        onChangeSpy(next);
        setPoints(next);
      }}
      {...props}
    />
  );
}

const canvas = () => screen.getByTestId('zone-canvas');
const handles = () => screen.queryAllByRole('button', { name: /^Point \d+ of \d+/ });
const click = (x, y) => fireEvent.click(canvas(), { clientX: x, clientY: y });

describe('PolygonEditor', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(RECT);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('adding points', () => {
    it('adds a point where the frame is clicked, as a fraction of the frame', () => {
      const spy = vi.fn();
      render(<Harness onChangeSpy={spy} />);
      click(100, 45);
      expect(spy).toHaveBeenLastCalledWith([[0.25, 0.2]]);
      expect(handles()).toHaveLength(1);
    });

    it('appends clicks in order', () => {
      const spy = vi.fn();
      render(<Harness onChangeSpy={spy} />);
      click(40, 45);
      click(360, 45);
      click(200, 200);
      expect(spy).toHaveBeenLastCalledWith([
        [0.1, 0.2],
        [0.9, 0.2],
        [0.5, 0.8889],
      ]);
    });

    it('inserts into an edge when the click lands on it', () => {
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      click(200, 45); // on the top edge, between points 1 and 2
      expect(spy).toHaveBeenLastCalledWith([TRIANGLE[0], [0.5, 0.2], TRIANGLE[1], TRIANGLE[2]]);
    });

    it('ignores a click on a frame that has no size yet', () => {
      HTMLElement.prototype.getBoundingClientRect.mockReturnValue({ ...RECT, width: 0, height: 0 });
      const spy = vi.fn();
      render(<Harness onChangeSpy={spy} />);
      click(100, 45);
      expect(spy).not.toHaveBeenCalled();
    });

    it('stops at the maximum number of points', () => {
      const full = Array.from({ length: MAX_POINTS }, (_, i) => [
        0.5 + 0.4 * Math.cos((i / MAX_POINTS) * 2 * Math.PI),
        0.5 + 0.4 * Math.sin((i / MAX_POINTS) * 2 * Math.PI),
      ]);
      const spy = vi.fn();
      render(<Harness initial={full} onChangeSpy={spy} />);
      expect(screen.getByRole('button', { name: 'Add point' })).toBeDisabled();
      click(200, 112); // the middle: clear of every edge
      expect(handles()).toHaveLength(MAX_POINTS);
    });
  });

  describe('the points', () => {
    it('are buttons that say where they are', () => {
      render(<Harness initial={TRIANGLE} />);
      expect(handles().map((h) => h.getAttribute('aria-label'))).toEqual([
        'Point 1 of 3, 20% across, 20% down',
        'Point 2 of 3, 80% across, 20% down',
        'Point 3 of 3, 50% across, 80% down',
      ]);
    });

    it('are placed by percentage of the frame', () => {
      render(<Harness initial={TRIANGLE} />);
      expect(handles()[1]).toHaveStyle({ left: '80%', top: '20%' });
    });

    it('move with the arrow keys, by 1% and by 5% with Shift', async () => {
      const user = userEvent.setup();
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      handles()[0].focus();
      await user.keyboard('{ArrowRight}');
      expect(spy).toHaveBeenLastCalledWith([[0.21, 0.2], TRIANGLE[1], TRIANGLE[2]]);
      await user.keyboard('{ArrowDown}');
      expect(spy).toHaveBeenLastCalledWith([[0.21, 0.21], TRIANGLE[1], TRIANGLE[2]]);
      await user.keyboard('{Shift>}{ArrowLeft}{/Shift}');
      expect(spy).toHaveBeenLastCalledWith([[0.16, 0.21], TRIANGLE[1], TRIANGLE[2]]);
      await user.keyboard('{Shift>}{ArrowUp}{/Shift}');
      expect(spy).toHaveBeenLastCalledWith([[0.16, 0.16], TRIANGLE[1], TRIANGLE[2]]);
    });

    it('stay inside the frame when nudged', async () => {
      const user = userEvent.setup();
      const spy = vi.fn();
      render(<Harness initial={[[0.995, 0.003], TRIANGLE[1], TRIANGLE[2]]} onChangeSpy={spy} />);
      handles()[0].focus();
      await user.keyboard('{ArrowRight}{ArrowUp}');
      expect(spy).toHaveBeenLastCalledWith([[1, 0], TRIANGLE[1], TRIANGLE[2]]);
    });

    it('are removed with Delete or Backspace, and focus moves to the next one', async () => {
      const user = userEvent.setup();
      render(<Harness initial={TRIANGLE} />);
      handles()[1].focus();
      await user.keyboard('{Delete}');
      expect(handles()).toHaveLength(2);
      expect(handles()[1]).toHaveFocus(); // what was point 3 is now point 2
      await user.keyboard('{Backspace}');
      expect(handles()).toHaveLength(1);
      expect(handles()[0]).toHaveFocus(); // the last one goes: focus falls back to the previous
    });

    it('are removed by a double-click', async () => {
      const user = userEvent.setup();
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      await user.dblClick(handles()[2]);
      expect(spy).toHaveBeenLastCalledWith([TRIANGLE[0], TRIANGLE[1]]);
    });

    it('do not add a point when one is clicked', async () => {
      const user = userEvent.setup();
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      await user.click(handles()[0]);
      expect(spy).not.toHaveBeenCalled();
    });

    it('can be dragged, and only while the pointer is down', () => {
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      const handle = handles()[0];
      fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 80, clientY: 45 });
      fireEvent.pointerMove(handle, { pointerId: 1, clientX: 200, clientY: 112.5 });
      expect(spy).toHaveBeenLastCalledWith([[0.5, 0.5], TRIANGLE[1], TRIANGLE[2]]);
      fireEvent.pointerMove(handle, { pointerId: 1, clientX: 400, clientY: 225 });
      expect(spy).toHaveBeenLastCalledWith([[1, 1], TRIANGLE[1], TRIANGLE[2]]);
      fireEvent.pointerUp(handle, { pointerId: 1 });
      spy.mockClear();
      fireEvent.pointerMove(handle, { pointerId: 1, clientX: 10, clientY: 10 });
      expect(spy).not.toHaveBeenCalled();
    });

    it('are not dragged by the secondary button', () => {
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      const handle = handles()[0];
      fireEvent.pointerDown(handle, { button: 2, pointerId: 1, clientX: 80, clientY: 45 });
      fireEvent.pointerMove(handle, { pointerId: 1, clientX: 200, clientY: 112 });
      expect(spy).not.toHaveBeenCalled();
    });

    it('drag only the point that was grabbed', () => {
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      fireEvent.pointerDown(handles()[0], { button: 0, pointerId: 1, clientX: 80, clientY: 45 });
      fireEvent.pointerMove(handles()[1], { pointerId: 1, clientX: 200, clientY: 112 });
      expect(spy).not.toHaveBeenCalled();
    });
  });

  describe('the toolbar', () => {
    it('adds a starter triangle without taking focus off the button', async () => {
      const user = userEvent.setup();
      render(<Harness />);
      const add = screen.getByRole('button', { name: 'Add point' });
      await user.click(add);
      await user.click(add);
      await user.click(add);
      expect(handles()).toHaveLength(3);
      expect(add).toHaveFocus();
      expect(screen.getByRole('status')).toHaveTextContent('3 points');
    });

    it('then splits the longest edge', async () => {
      const user = userEvent.setup();
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} />);
      await user.click(screen.getByRole('button', { name: 'Add point' }));
      expect(spy).toHaveBeenLastCalledWith([TRIANGLE[0], [0.5, 0.2], TRIANGLE[1], TRIANGLE[2]]);
    });

    it('removes the last point, and clears the outline', async () => {
      const user = userEvent.setup();
      render(<Harness initial={TRIANGLE} />);
      await user.click(screen.getByRole('button', { name: 'Remove last point' }));
      expect(handles()).toHaveLength(2);
      await user.click(screen.getByRole('button', { name: 'Clear outline' }));
      expect(handles()).toHaveLength(0);
      expect(screen.getByRole('button', { name: 'Remove last point' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Clear outline' })).toBeDisabled();
      expect(screen.getByRole('status')).toHaveTextContent('0 points');
    });

    it('does not move focus onto a point when the last one is removed', async () => {
      const user = userEvent.setup();
      render(<Harness initial={TRIANGLE} />);
      const remove = screen.getByRole('button', { name: 'Remove last point' });
      await user.click(remove);
      expect(remove).toHaveFocus();
    });

    it('says "1 point" in the singular', () => {
      render(<Harness initial={[[0.5, 0.5]]} />);
      expect(screen.getByRole('status')).toHaveTextContent(/^1 point$/);
    });
  });

  describe('the drawing', () => {
    const polygons = () => canvas().querySelectorAll('polygon');

    it('is a filled polygon from three points, a line at two, and nothing before', () => {
      const { rerender } = render(<PolygonEditor points={[]} onChange={() => {}} />);
      expect(canvas().querySelector('polygon, polyline')).toBeNull();
      rerender(<PolygonEditor points={TRIANGLE.slice(0, 2)} onChange={() => {}} />);
      expect(canvas().querySelector('polyline')).not.toBeNull();
      expect(canvas().querySelector('polygon')).toBeNull();
      rerender(<PolygonEditor points={TRIANGLE} onChange={() => {}} />);
      expect(canvas().querySelector('polygon')).not.toBeNull();
      expect(canvas().querySelector('polyline')).toBeNull();
    });

    it('draws the points in the 0..1 box as given', () => {
      render(<PolygonEditor points={TRIANGLE} onChange={() => {}} />);
      expect(polygons()[0]).toHaveAttribute('points', '0.2,0.2 0.8,0.2 0.5,0.8');
    });

    it('shows the camera frame, and still works without one', () => {
      const { rerender } = render(
        <PolygonEditor frameUrl="blob:frame" points={[]} onChange={() => {}} />,
      );
      expect(screen.getByAltText('Camera frame to draw the zone on')).toHaveAttribute(
        'src',
        'blob:frame',
      );
      rerender(<PolygonEditor points={[]} onChange={() => {}} />);
      expect(screen.queryByAltText('Camera frame to draw the zone on')).toBeNull();
    });

    it('draws the camera’s other zones quietly, named, underneath', () => {
      const other = [
        {
          id: 'z1',
          name: 'Loading bay',
          polygon: [
            [0.1, 0.1],
            [0.3, 0.1],
            [0.2, 0.3],
          ],
        },
      ];
      render(<PolygonEditor points={TRIANGLE} otherZones={other} onChange={() => {}} />);
      expect(screen.getByText('Loading bay')).toBeInTheDocument();
      expect(polygons()).toHaveLength(2);
      expect(polygons()[0]).toHaveAttribute('points', '0.1,0.1 0.3,0.1 0.2,0.3'); // underneath
      // Dashed and glowing, so it can be seen on any footage rather than only on a plain one.
      expect(polygons()[0]).toHaveAttribute('stroke-dasharray', '8 5');
      expect(polygons()[0].style.filter).toContain('drop-shadow');
    });

    it('makes the frame match the stream’s aspect ratio', () => {
      const { container } = render(
        <PolygonEditor aspect={4 / 3} points={[]} onChange={() => {}} />,
      );
      expect(container.querySelector('[style*="aspect-ratio"]')).toHaveStyle({
        aspectRatio: String(4 / 3),
      });
    });
  });

  describe('when disabled (a viewer or operator may look but not draw)', () => {
    it('ignores clicks, keys and drags, and hides the toolbar', async () => {
      const user = userEvent.setup();
      const spy = vi.fn();
      render(<Harness initial={TRIANGLE} onChangeSpy={spy} disabled />);
      click(100, 45);
      handles().forEach((handle) => expect(handle).toBeDisabled());
      fireEvent.keyDown(handles()[0], { key: 'Delete' });
      fireEvent.pointerDown(handles()[0], { button: 0, pointerId: 1 });
      fireEvent.pointerMove(handles()[0], { pointerId: 1, clientX: 5, clientY: 5 });
      await user.dblClick(handles()[0]);
      expect(spy).not.toHaveBeenCalled();
      expect(screen.queryByRole('button', { name: 'Add point' })).toBeNull();
      expect(canvas()).not.toHaveClass('cursor-crosshair');
    });
  });

  describe('what a person can rely on', () => {
    it('gives a point focus when it is grabbed, so the arrow keys work straight away', () => {
      // Safari does not focus a button that is clicked, so the editor does it itself.
      render(<Harness initial={TRIANGLE} />);
      const handle = handles()[1];
      fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 320, clientY: 45 });
      expect(handle).toHaveFocus();
    });

    it('puts each other zone’s name at the middle of its outline', () => {
      const other = [
        {
          id: 'z1',
          name: 'Loading bay',
          polygon: [
            [0.1, 0.2],
            [0.5, 0.2],
            [0.3, 0.8],
          ],
        },
      ];
      render(<PolygonEditor points={[]} otherZones={other} onChange={() => {}} />);
      const label = screen.getByText('Loading bay');
      expect(parseFloat(label.style.left)).toBeCloseTo(30, 3);
      expect(parseFloat(label.style.top)).toBeCloseTo(40, 3);
    });
  });
});
