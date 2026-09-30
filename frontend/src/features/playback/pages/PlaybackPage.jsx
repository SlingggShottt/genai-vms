import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { useCameras } from '@/features/cameras/api';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { hlsAuthConfig, playlistUrl, useRecordingDensity } from '../api';
import { TimelineScrubber } from '../components/TimelineScrubber';
import { playerTimeToWallClock, wallClockToPlayerTime } from '../lib/programDateTime';

const ONE_HOUR_MS = 60 * 60 * 1000;

function toDatetimeLocalValue(date) {
  // datetime-local wants "YYYY-MM-DDTHH:mm" in the *browser's* local time,
  // with no timezone suffix — toISOString() is UTC, so build it from the
  // local field getters instead.
  const pad = (n) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

function defaultRange() {
  const end = new Date();
  const start = new Date(end.getTime() - ONE_HOUR_MS);
  return { start: toDatetimeLocalValue(start), end: toDatetimeLocalValue(end) };
}

export function PlaybackPage() {
  const { data: cameras } = useCameras();
  const enabledCameras = cameras?.items.filter((c) => c.enabled) ?? [];

  const [cameraCode, setCameraCode] = useState('');
  const [draftRange, setDraftRange] = useState(defaultRange);
  const [activeRange, setActiveRange] = useState(null); // { startIso, endIso, startDate, endDate }
  const [playheadMs, setPlayheadMs] = useState(null);
  const [playerError, setPlayerError] = useState(null);

  const videoRef = useRef(null);
  const fragmentsRef = useRef([]);

  useEffect(() => {
    if (enabledCameras.length > 0 && !cameraCode) {
      setCameraCode(enabledCameras[0].code);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only seed the default once cameras load
  }, [enabledCameras.length]);

  const { data: density } = useRecordingDensity(
    cameraCode,
    activeRange?.startIso,
    activeRange?.endIso,
  );

  useEffect(() => {
    const videoEl = videoRef.current;
    if (!videoEl || !cameraCode || !activeRange) return undefined;

    setPlayerError(null);
    fragmentsRef.current = [];
    let hls = null;
    let cancelled = false;

    function handleTimeUpdate() {
      const wallClockMs = playerTimeToWallClock(fragmentsRef.current, videoEl.currentTime);
      if (wallClockMs != null) setPlayheadMs(wallClockMs);
    }
    videoEl.addEventListener('timeupdate', handleTimeUpdate);

    const url = playlistUrl(cameraCode, activeRange.startIso, activeRange.endIso);
    if (Hls.isSupported()) {
      hls = new Hls(hlsAuthConfig());
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal && !cancelled) setPlayerError('Playback failed. Try a different range.');
      });
      hls.on(Hls.Events.LEVEL_LOADED, (_event, data) => {
        if (!cancelled) fragmentsRef.current = data.details.fragments;
      });
      hls.loadSource(url);
      hls.attachMedia(videoEl);
    } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
      videoEl.src = url;
    } else {
      setPlayerError('This browser cannot play HLS video.');
    }

    return () => {
      cancelled = true;
      videoEl.removeEventListener('timeupdate', handleTimeUpdate);
      hls?.destroy();
    };
  }, [cameraCode, activeRange]);

  function handleLoad(event) {
    event.preventDefault();
    const startDate = new Date(draftRange.start);
    const endDate = new Date(draftRange.end);
    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return;
    if (endDate <= startDate) return;
    setActiveRange({
      startDate,
      endDate,
      startIso: startDate.toISOString(),
      endIso: endDate.toISOString(),
    });
    setPlayheadMs(startDate.getTime());
  }

  function handleScrub(wallClockMs) {
    setPlayheadMs(wallClockMs);
    const playerTime = wallClockToPlayerTime(fragmentsRef.current, wallClockMs);
    const videoEl = videoRef.current;
    if (playerTime != null && videoEl) videoEl.currentTime = playerTime;
  }

  const rangeInvalid =
    activeRange == null &&
    (!draftRange.start ||
      !draftRange.end ||
      new Date(draftRange.end) <= new Date(draftRange.start));

  if (cameras && enabledCameras.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-center text-text-muted">
        <p>No cameras yet. Add a camera in Settings to start recording.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <form onSubmit={handleLoad} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="playback-camera">Camera</Label>
          <select
            id="playback-camera"
            value={cameraCode}
            onChange={(e) => setCameraCode(e.target.value)}
            className="h-9 rounded-panel border border-rule bg-surface px-3 text-sm text-text"
          >
            {enabledCameras.map((c) => (
              <option key={c.id} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="playback-start">Start</Label>
          <input
            id="playback-start"
            type="datetime-local"
            value={draftRange.start}
            onChange={(e) => setDraftRange((prev) => ({ ...prev, start: e.target.value }))}
            className="h-9 rounded-panel border border-rule bg-surface px-3 text-sm text-text"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="playback-end">End</Label>
          <input
            id="playback-end"
            type="datetime-local"
            value={draftRange.end}
            onChange={(e) => setDraftRange((prev) => ({ ...prev, end: e.target.value }))}
            className="h-9 rounded-panel border border-rule bg-surface px-3 text-sm text-text"
          />
        </div>

        <Button type="submit" disabled={!cameraCode || rangeInvalid}>
          Load
        </Button>
      </form>

      <div
        className={cn(
          'relative aspect-video max-h-[60vh] overflow-hidden rounded-tile bg-video-bg',
        )}
      >
        {/* eslint-disable-next-line jsx-a11y/media-has-caption -- recorded
            camera footage has no caption track to provide; there's nothing
            to attach */}
        <video ref={videoRef} controls className="h-full w-full object-contain" />
        {playerError && (
          <div className="pointer-events-none absolute inset-0 flex select-none items-center justify-center bg-video-bg text-sm text-text-muted">
            {playerError}
          </div>
        )}
        {!activeRange && (
          <div className="pointer-events-none absolute inset-0 flex select-none items-center justify-center bg-video-bg text-sm text-text-muted">
            Choose a camera and time range, then Load.
          </div>
        )}
      </div>

      {activeRange && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-text-muted">
            {formatDateTime(activeRange.startDate)} – {formatDateTime(activeRange.endDate)}
          </p>
          <TimelineScrubber
            buckets={density?.buckets ?? []}
            rangeStart={activeRange.startDate}
            rangeEnd={activeRange.endDate}
            playheadMs={playheadMs ?? activeRange.startDate.getTime()}
            onScrub={handleScrub}
          />
        </div>
      )}
    </div>
  );
}
