import { useEffect, useRef } from 'react';
import { playerTimeToWallClock } from '../lib/programDateTime';

// A frame more than this far (in wall-clock ms) from the current playhead
// is stale — perception didn't cover that instant (segment boundary, gap,
// or the window just hasn't loaded yet) — so nothing is drawn rather than
// showing boxes that visibly don't track the video.
const STALE_FRAME_MS = 1000;

const BOX_STROKE_WIDTH = 1.5;
const LABEL_FONT = '600 11px "IBM Plex Sans", system-ui, sans-serif';

function nearestFrame(frames, wallClockMs) {
  if (!frames || frames.length === 0 || wallClockMs == null) return null;
  let best = null;
  let bestDiff = Infinity;
  for (const frame of frames) {
    const diff = Math.abs(new Date(frame.ts).getTime() - wallClockMs);
    if (diff < bestDiff) {
      best = frame;
      bestDiff = diff;
    }
  }
  return best && bestDiff <= STALE_FRAME_MS ? best : null;
}

/** Maps the video's intrinsic frame onto the container's box under
 * `object-contain` (the video element's own CSS), so normalized bbox
 * coordinates land on the actual rendered picture rather than the
 * letterboxed container.
 */
function contentRect(containerW, containerH, videoW, videoH) {
  if (!videoW || !videoH) return { x: 0, y: 0, w: containerW, h: containerH };
  const containerRatio = containerW / containerH;
  const videoRatio = videoW / videoH;
  if (videoRatio > containerRatio) {
    const w = containerW;
    const h = containerW / videoRatio;
    return { x: 0, y: (containerH - h) / 2, w, h };
  }
  const h = containerH;
  const w = containerH * videoRatio;
  return { x: (containerW - w) / 2, y: 0, w, h };
}

/** Canvas overlay drawing bboxes + track ids synchronized with the player
 * (P2-J6, FR-PLAY-03). Reads `videoEl.currentTime` on a `requestAnimationFrame`
 * loop rather than React state (which only updates on `timeupdate`, too
 * coarse for the <= 200ms drift AC) and maps it to wall-clock time with
 * the same `playerTimeToWallClock` the scrubber uses, so the overlay and
 * the timeline agree on "now" by construction.
 *
 * `frames` is `/twin/{camera}/frames`'s response for whatever window
 * currently covers the playhead (`useTwinFrames` in `../api.js`).
 * `fragmentsRef` is the hls.js fragments list `PlaybackPage` already
 * tracks for the scrubber's own player-time <-> wall-clock mapping.
 */
export function DetectionOverlay({ videoRef, fragmentsRef, frames, enabled, onSelectTrack }) {
  const canvasRef = useRef(null);
  const boxesRef = useRef([]); // last-drawn screen-space rects, for click hit-testing

  useEffect(() => {
    const canvas = canvasRef.current;
    const videoEl = videoRef.current;
    if (!canvas || !videoEl) return undefined;

    const ctx = canvas.getContext('2d');
    let rafId = null;
    let cancelled = false;

    function resizeCanvas() {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
    }

    // Observes the canvas's own box (not the video container's) — its
    // bottom edge moves when `enabled` toggles the reserved strip for the
    // native video control bar below, and this fires on that too.
    const resizeObserver = new ResizeObserver(resizeCanvas);
    resizeObserver.observe(canvas);
    resizeCanvas();

    const accentColor =
      getComputedStyle(canvas).getPropertyValue('--accent').trim() || '#5ec4cf';
    const accentInk = getComputedStyle(canvas).getPropertyValue('--accent-ink').trim() || '#0e2a2e';

    function draw() {
      if (cancelled) return;
      rafId = requestAnimationFrame(draw);
      if (!enabled) {
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        boxesRef.current = [];
        return;
      }

      const dpr = window.devicePixelRatio || 1;
      const wallClockMs = playerTimeToWallClock(fragmentsRef.current, videoEl.currentTime);
      const frame = nearestFrame(frames, wallClockMs);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      boxesRef.current = [];
      if (!frame) return;

      const content = contentRect(
        canvas.width,
        canvas.height,
        videoEl.videoWidth,
        videoEl.videoHeight,
      );

      ctx.lineWidth = BOX_STROKE_WIDTH * dpr;
      ctx.strokeStyle = accentColor;
      ctx.font = LABEL_FONT.replace('11px', `${11 * dpr}px`);
      ctx.textBaseline = 'bottom';

      for (const obj of frame.objects) {
        const [x1, y1, x2, y2] = obj.bbox;
        const screenX = content.x + x1 * content.w;
        const screenY = content.y + y1 * content.h;
        const screenW = (x2 - x1) * content.w;
        const screenH = (y2 - y1) * content.h;

        ctx.strokeRect(screenX, screenY, screenW, screenH);

        const label = obj.track_id;
        const labelPadding = 3 * dpr;
        const labelHeight = 14 * dpr;
        const labelWidth = ctx.measureText(label).width + labelPadding * 2;
        const labelY = Math.max(labelHeight, screenY);
        ctx.fillStyle = accentColor;
        ctx.fillRect(screenX, labelY - labelHeight, labelWidth, labelHeight);
        ctx.fillStyle = accentInk;
        ctx.fillText(label, screenX + labelPadding, labelY - 2 * dpr);

        boxesRef.current.push({
          trackId: obj.track_id,
          x: screenX / dpr,
          y: screenY / dpr,
          w: screenW / dpr,
          h: screenH / dpr,
        });
      }
    }

    rafId = requestAnimationFrame(draw);
    return () => {
      cancelled = true;
      if (rafId != null) cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
    };
  }, [videoRef, fragmentsRef, frames, enabled]);

  function handleClick(event) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const clickX = event.clientX - rect.left;
    const clickY = event.clientY - rect.top;
    const hit = boxesRef.current.find(
      (box) =>
        clickX >= box.x && clickX <= box.x + box.w && clickY >= box.y && clickY <= box.y + box.h,
    );
    if (hit) onSelectTrack(hit.trackId);
  }

  return (
    <canvas
      ref={canvasRef}
      onClick={handleClick}
      // Leaves the native <video controls> bar (bottom ~40px) clickable
      // when overlays are on — the canvas would otherwise sit on top and
      // swallow play/pause/seek/volume clicks. When overlays are off the
      // canvas is fully click-through.
      className={
        enabled
          ? 'absolute inset-x-0 top-0 bottom-10 cursor-pointer'
          : 'absolute inset-0 pointer-events-none'
      }
      aria-hidden="true"
    />
  );
}
