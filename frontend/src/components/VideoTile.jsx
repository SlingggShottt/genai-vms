import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { connectWhep, hlsUrl } from '@/lib/mediamtx';
import { formatClock } from '@/lib/time';
import { cn } from '@/lib/utils';

const STATUS_DOT_CLASS = {
  online: 'bg-ok',
  reconnecting: 'bg-sev-high',
  offline: 'bg-text-muted',
};

// A WHEP exchange can succeed and still never deliver video — MediaMTX closes
// the session of an H.264 stream with B-frames (WebRTC can't carry them), and
// the browser reports the connection `failed` only ~15 s later. A healthy
// session shows its first frame within a second, so give it this long, then
// fall back to HLS (which handles B-frames).
const FIRST_FRAME_TIMEOUT_MS = 5000;

/** A single camera feed per docs/style_guide.md §B.7: black background,
 * 2px radius, camera name + status dot overlay top-left, wall-clock
 * bottom-left, no gradients over the video. Tries WebRTC (WHEP) first for
 * low latency, falls back to HLS via hls.js on failure (FR-LIVE-01).
 */
export function VideoTile({ camera, focused = false, onDoubleClick }) {
  const videoRef = useRef(null);
  const [playbackState, setPlaybackState] = useState('connecting');
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    const videoEl = videoRef.current;
    if (!videoEl) return undefined;

    let cancelled = false;
    let closeWhep = null;
    let hls = null;
    let fellBack = false;
    let frameTimer = null;
    const controller = new AbortController();

    function onFirstFrame() {
      clearTimeout(frameTimer);
    }

    function startHlsFallback() {
      if (cancelled || fellBack) return;
      fellBack = true;
      // A media element plays its `srcObject` in preference to `src`, which is
      // what hls.js attaches — so the (dead) WebRTC MediaStream must go first.
      videoEl.srcObject = null;
      if (Hls.isSupported()) {
        hls = new Hls();
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (data.fatal && !cancelled) setPlaybackState('error');
        });
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          if (!cancelled) setPlaybackState('hls');
        });
        hls.loadSource(hlsUrl(camera.code));
        hls.attachMedia(videoEl);
      } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
        videoEl.src = hlsUrl(camera.code);
        setPlaybackState('hls');
      } else {
        setPlaybackState('error');
      }
    }

    // WebRTC negotiated but isn't usable (no frame in time, or the connection
    // failed/closed on its own): release it and play HLS instead.
    function dropWebrtcForHls() {
      if (cancelled || fellBack) return;
      clearTimeout(frameTimer);
      videoEl.removeEventListener('loadeddata', onFirstFrame);
      closeWhep?.();
      closeWhep = null;
      startHlsFallback();
    }

    setPlaybackState('connecting');
    connectWhep(videoEl, camera.code, {
      signal: controller.signal,
      onConnectionLost: dropWebrtcForHls,
    })
      .then((close) => {
        if (cancelled || fellBack) {
          close();
          return;
        }
        closeWhep = close;
        setPlaybackState('webrtc');
        if (videoEl.readyState >= 2) return; // a frame is already showing
        videoEl.addEventListener('loadeddata', onFirstFrame, { once: true });
        frameTimer = setTimeout(dropWebrtcForHls, FIRST_FRAME_TIMEOUT_MS);
      })
      .catch(() => {
        startHlsFallback();
      });

    return () => {
      cancelled = true;
      clearTimeout(frameTimer);
      videoEl.removeEventListener('loadeddata', onFirstFrame);
      controller.abort();
      closeWhep?.();
      hls?.destroy();
    };
  }, [camera.code]);

  return (
    <div
      onDoubleClick={onDoubleClick}
      className={cn(
        'relative aspect-video overflow-hidden rounded-tile bg-video-bg',
        focused && 'ring-2 ring-accent',
      )}
    >
      <video ref={videoRef} autoPlay playsInline muted className="h-full w-full object-cover" />

      {playbackState === 'error' && (
        <div className="pointer-events-none absolute inset-0 flex select-none items-center justify-center bg-video-bg text-sm text-text-muted">
          No signal
        </div>
      )}

      <div className="pointer-events-none absolute left-2 top-2 flex items-center gap-1.5">
        <span
          className={cn('h-2 w-2 rounded-pill', STATUS_DOT_CLASS[camera.status] ?? 'bg-text-muted')}
          aria-hidden="true"
        />
        <span className="font-condensed text-sm font-medium text-white drop-shadow">
          {camera.name}
        </span>
      </div>
      <span className="sr-only">
        Camera {camera.name}, status: {camera.status}
      </span>

      <div className="pointer-events-none absolute bottom-2 left-2 text-xs tabular-nums text-white drop-shadow">
        {formatClock(now)}
      </div>
    </div>
  );
}
