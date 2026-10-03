import { useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import {
  MAX_POINTS,
  addPoint,
  centroid,
  movePoint,
  nudge,
  removePoint,
  suggestedInsertion,
  toNormalized,
} from '../polygon';

const STEP = 0.01;
const BIG_STEP = 0.05;
const ARROWS = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

const percent = (value) => Math.round(value * 100);
const toSvgPoints = (points) => points.map(([x, y]) => `${x},${y}`).join(' ');

/** Draws a zone outline over a still camera frame (FR-CAM-03).
 *
 * `points` are normalised 0..1 of the frame and are controlled: every change goes out through
 * `onChange`. Click the frame to add a point (onto an edge when you hit one), drag a point to
 * move it. Each point is a real button, so it is reachable by Tab; the arrow keys nudge it (Shift
 * for bigger steps) and Delete removes it. "Add point" does the same job as a click for anyone
 * who can't aim at the frame. `otherZones` are drawn quietly underneath, for context.
 */
export function PolygonEditor({
  frameUrl,
  aspect = 16 / 9,
  points,
  onChange,
  otherZones = [],
  disabled = false,
}) {
  const frameRef = useRef(null);
  const handleRefs = useRef([]);
  const dragging = useRef(null);
  // After a point is added or removed the focus should land on a neighbour, not fall to <body>.
  const focusAfterRender = useRef(null);

  useEffect(() => {
    if (focusAfterRender.current === null) return;
    handleRefs.current[focusAfterRender.current]?.focus();
    focusAfterRender.current = null;
  });

  const pointAt = (event) =>
    toNormalized(event.clientX, event.clientY, frameRef.current?.getBoundingClientRect());

  function handleFrameClick(event) {
    if (disabled) return;
    const point = pointAt(event);
    if (!point) return;
    onChange(addPoint(points, point, aspect));
  }

  // Keeps focus where the user is: the toolbar button they pressed stays focused, so "Add point"
  // can be pressed three times in a row from the keyboard.
  function handleAddPoint() {
    const { index, point } = suggestedInsertion(points, aspect);
    onChange([...points.slice(0, index), point, ...points.slice(index)]);
  }

  // Removing a point from the point itself moves focus to its neighbour instead of losing it.
  function remove(index, { refocus = false } = {}) {
    focusAfterRender.current =
      refocus && points.length > 1 ? Math.min(index, points.length - 2) : null;
    onChange(removePoint(points, index));
  }

  function handlePointerDown(event, index) {
    if (disabled || event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.currentTarget.focus();
    dragging.current = index;
  }

  function handlePointerMove(event, index) {
    if (dragging.current !== index) return;
    const point = pointAt(event);
    if (point) onChange(movePoint(points, index, point));
  }

  const stopDragging = () => {
    dragging.current = null;
  };

  function handleKeyDown(event, index) {
    if (disabled) return;
    const arrow = ARROWS[event.key];
    if (arrow) {
      event.preventDefault();
      const step = event.shiftKey ? BIG_STEP : STEP;
      onChange(movePoint(points, index, nudge(points[index], arrow[0] * step, arrow[1] * step)));
    } else if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      remove(index, { refocus: true });
    }
  }

  return (
    <div>
      <div
        ref={frameRef}
        className="relative w-full select-none overflow-hidden rounded-tile bg-video-bg"
        style={{ aspectRatio: aspect }}
      >
        {frameUrl && (
          <img
            src={frameUrl}
            alt="Camera frame to draw the zone on"
            draggable={false}
            className="absolute inset-0 h-full w-full"
          />
        )}

        {/* A 0..1 box stretched over the frame, so points are used as they are. Strokes keep
            their width when stretched; round handles and labels are HTML for that reason. */}
        <svg
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          aria-hidden="true"
          data-testid="zone-canvas"
          className={
            disabled
              ? 'absolute inset-0 h-full w-full'
              : 'absolute inset-0 h-full w-full cursor-crosshair'
          }
          onClick={handleFrameClick}
        >
          {otherZones.map((zone) => (
            <polygon
              key={zone.id}
              points={toSvgPoints(zone.polygon)}
              fill="none"
              strokeDasharray="8 5"
              vectorEffect="non-scaling-stroke"
              className="stroke-text"
              strokeWidth="2"
              // A dark glow, so the outline reads on bright and dark footage alike.
              style={{ filter: 'drop-shadow(0 0 2px var(--video-bg))' }}
            />
          ))}
          {points.length >= 3 ? (
            <polygon
              points={toSvgPoints(points)}
              vectorEffect="non-scaling-stroke"
              strokeWidth="2"
              className="fill-accent-tint stroke-accent"
            />
          ) : (
            points.length === 2 && (
              <polyline
                points={toSvgPoints(points)}
                fill="none"
                vectorEffect="non-scaling-stroke"
                strokeWidth="2"
                className="stroke-accent"
              />
            )
          )}
        </svg>

        {otherZones.map((zone) => {
          const [x, y] = centroid(zone.polygon);
          return (
            <span
              key={zone.id}
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 font-condensed text-xs font-medium text-white drop-shadow"
              style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
            >
              {zone.name}
            </span>
          );
        })}

        {points.map(([x, y], index) => (
          <button
            // Handles carry no state of their own, so the index is a fine key.
            key={index}
            ref={(element) => {
              handleRefs.current[index] = element;
            }}
            type="button"
            disabled={disabled}
            aria-label={`Point ${index + 1} of ${points.length}, ${percent(x)}% across, ${percent(y)}% down`}
            className="absolute z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none rounded-pill border-2 border-accent bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-video-bg active:cursor-grabbing"
            style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
            onPointerDown={(event) => handlePointerDown(event, index)}
            onPointerMove={(event) => handlePointerMove(event, index)}
            onPointerUp={stopDragging}
            onPointerCancel={stopDragging}
            onKeyDown={(event) => handleKeyDown(event, index)}
            onDoubleClick={() => remove(index, { refocus: true })}
          />
        ))}
      </div>

      {!disabled && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleAddPoint}
            disabled={points.length >= MAX_POINTS}
          >
            Add point
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => remove(points.length - 1)}
            disabled={points.length === 0}
          >
            Remove last point
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onChange([])}
            disabled={points.length === 0}
          >
            Clear outline
          </Button>
          <p role="status" className="text-sm text-text-muted tabular-nums">
            {points.length === 1 ? '1 point' : `${points.length} points`}
          </p>
          <p className="w-full text-xs text-text-muted">
            Click the frame to add a point, drag to move it. With a point selected, arrow keys nudge
            it and Delete removes it.
          </p>
        </div>
      )}
    </div>
  );
}
