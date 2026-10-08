import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Hls from 'hls.js';
import { Pause, Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PHASE_LABEL } from '@/features/incidents/lib';
import { formatClock, formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { hlsAuthConfig, playlistUrl } from '../api';
import { coversWallClock } from '../lib/programDateTime';
import { advancePlayhead, clipPhases, planSync, rateFor } from '../lib/sync';
import { CameraLanes } from './CameraLanes';

export const MAX_VIEWS = 4;
const TICK_MS = 100;
// After a seek or a start the picture needs a moment to settle; drift is not counted in that time.
const SETTLE_MS = 1500;
// A view that was just pulled back is left alone for this long, so a slow download is not seeked
// again and again.
const RESEEK_MS = 1000;

const Pane = memo(function Pane({ camera, label, startIso, endIso, register, gap }) {
  const videoRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;
    setError(null);
    const entry = { video, fragments: [], lastSeek: 0 };
    register(camera, entry);
    let hls = null;
    let cancelled = false;
    const url = playlistUrl(camera, startIso, endIso);
    if (Hls.isSupported()) {
      hls = new Hls(hlsAuthConfig());
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal && !cancelled) setError('Playback failed for this camera.');
      });
      hls.on(Hls.Events.LEVEL_LOADED, (_event, data) => {
        if (!cancelled) entry.fragments = data.details.fragments;
      });
      hls.loadSource(url);
      hls.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
    } else {
      setError('This browser cannot play HLS video.');
    }
    return () => {
      cancelled = true;
      hls?.destroy();
      register(camera, null);
    };
  }, [camera, startIso, endIso, register]);

  const notice = error ?? (gap ? 'No recording at this time.' : null);
  return (
    <figure className="relative aspect-video overflow-hidden rounded-tile bg-video-bg">
      <video ref={videoRef} muted playsInline className="h-full w-full object-contain" />
      <figcaption className="absolute left-2 top-2 rounded-tile bg-surface/80 px-2 py-0.5 text-xs text-text">
        {label}
      </figcaption>
      {notice && (
        <div
          role="status"
          className="absolute inset-0 flex items-center justify-center bg-video-bg text-sm text-text-muted"
        >
          {notice}
        </div>
      )}
    </figure>
  );
});

/** Up to four cameras played together from one playhead (FR-INV-02, P6-J4; the reasoning view's
 * "play all views for that phase", P5-J5). One clock drives every picture: each camera's
 * `<video>` is pulled back to it whenever it is more than 300 ms off, a camera that recorded
 * nothing at that moment says so and waits, and the clock stands still while any camera with
 * footage is still buffering. `data-max-drift-ms` / `data-corrections` on the status line are what
 * was measured while playing (settling time after a seek excluded).
 *
 * `views`: `[{ camera: code, label }]`; `timeline`: the incident's phase spans (optional);
 * `activePhase` / `onSelectPhase` let a parent drive and follow the phase being played.
 */
export function SyncedPlayer({
  views,
  startIso,
  endIso,
  timeline,
  activePhase,
  onSelectPhase,
  className,
}) {
  const shown = useMemo(() => views.slice(0, MAX_VIEWS), [views]);
  const startMs = Date.parse(startIso);
  const endMs = Date.parse(endIso);
  const spans = useMemo(() => clipPhases(timeline, startMs, endMs), [timeline, startMs, endMs]);

  const registry = useRef(new Map());
  const register = useCallback((key, entry) => {
    if (entry) registry.current.set(key, entry);
    else registry.current.delete(key);
  }, []);

  const clock = useRef({
    masterMs: startMs,
    playing: false,
    last: performance.now(),
    stopAtMs: null,
    settleUntil: 0,
    maxDrift: 0,
    samples: 0,
    corrections: 0,
  });
  const [ui, setUi] = useState({ masterMs: startMs, playing: false, gaps: '', maxDrift: 0 });

  const tick = useCallback(() => {
    const s = clock.current;
    const now = performance.now();
    const dt = Math.min(now - s.last, 1000);
    s.last = now;
    const entries = [...registry.current.entries()];
    const covering = entries.filter(([, e]) => coversWallClock(e.fragments, s.masterMs));
    const buffering = s.playing && covering.some(([, e]) => e.video.readyState < 3);
    s.masterMs = advancePlayhead({
      masterMs: s.masterMs,
      dtMs: dt,
      playing: s.playing,
      buffering,
      endMs,
    });
    if (s.stopAtMs != null && s.masterMs >= s.stopAtMs) {
      s.masterMs = s.stopAtMs;
      s.stopAtMs = null;
      s.playing = false;
    }
    if (s.masterMs >= endMs) s.playing = false;

    const plan = planSync(
      s.masterMs,
      entries.map(([key, e]) => ({
        key,
        fragments: e.fragments,
        currentTime: e.video.currentTime,
      })),
    );
    const wantPlaying = s.playing && !buffering;
    const gaps = [];
    const drifts = [];
    for (const p of plan) {
      const entry = registry.current.get(p.key);
      if (!entry) continue;
      const { video } = entry;
      if (p.state === 'gap') {
        gaps.push(p.key);
        if (!video.paused) video.pause();
        video.playbackRate = 1;
        continue;
      }
      if (p.state === 'loading') continue;
      drifts.push(`${p.key}:${Math.round(p.driftMs)}`);
      const settled = now >= s.settleUntil;
      if (s.playing && settled && !buffering) {
        s.maxDrift = Math.max(s.maxDrift, Math.abs(p.driftMs));
        s.samples += 1;
      }
      if (p.state === 'seek' && now - entry.lastSeek > RESEEK_MS) {
        video.currentTime = p.playerTime;
        entry.lastSeek = now;
        video.playbackRate = 1;
        if (s.playing && settled) s.corrections += 1;
      } else if (p.state === 'ok') {
        // a small gap is closed by running a little fast or slow, not by a jump
        const rate = wantPlaying ? rateFor(p.driftMs, video.playbackRate) : 1;
        if (video.playbackRate !== rate) video.playbackRate = rate;
      }
      if (wantPlaying && video.paused) video.play().catch(() => {});
      if (!wantPlaying && !video.paused) video.pause();
    }
    setUi((prev) => {
      const next = {
        masterMs: s.masterMs,
        playing: s.playing,
        gaps: gaps.sort().join(','),
        maxDrift: Math.round(s.maxDrift),
        drifts: drifts.join(','),
        corrections: s.corrections,
        samples: s.samples,
      };
      return prev.masterMs === next.masterMs &&
        prev.playing === next.playing &&
        prev.gaps === next.gaps &&
        prev.maxDrift === next.maxDrift &&
        prev.drifts === next.drifts
        ? prev
        : next;
    });
  }, [endMs]);

  useEffect(() => {
    clock.current.last = performance.now();
    const timer = setInterval(tick, TICK_MS);
    return () => clearInterval(timer);
  }, [tick]);

  // A new range starts again from its beginning.
  useEffect(() => {
    const s = clock.current;
    Object.assign(s, {
      masterMs: startMs,
      playing: false,
      stopAtMs: null,
      maxDrift: 0,
      samples: 0,
      corrections: 0,
    });
    s.settleUntil = performance.now() + SETTLE_MS;
  }, [startMs, endMs]);

  const seek = useCallback(
    (ms) => {
      const s = clock.current;
      s.masterMs = Math.min(Math.max(ms, startMs), endMs);
      s.stopAtMs = null;
      s.settleUntil = performance.now() + SETTLE_MS;
      for (const e of registry.current.values()) e.lastSeek = 0;
      tick();
    },
    [startMs, endMs, tick],
  );

  function togglePlay() {
    const s = clock.current;
    if (s.playing) {
      s.playing = false;
    } else {
      if (s.masterMs >= endMs) s.masterMs = startMs;
      s.playing = true;
      s.stopAtMs = null;
      s.settleUntil = performance.now() + SETTLE_MS;
    }
    tick();
  }

  const playPhase = useCallback(
    (phase) => {
      const span = spans.find((x) => x.phase === phase);
      if (!span) return;
      const s = clock.current;
      s.masterMs = span.startMs;
      s.stopAtMs = span.endMs;
      s.playing = true;
      s.settleUntil = performance.now() + SETTLE_MS;
      for (const e of registry.current.values()) e.lastSeek = 0;
      tick();
    },
    [spans, tick],
  );

  // The parent chose a phase (its own band, or a press on one of ours): play it, all views together.
  useEffect(() => {
    if (activePhase) playPhase(activePhase);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the chosen phase changes
  }, [activePhase]);

  // Choosing a phase that is not the chosen one tells the parent (which then drives `activePhase`);
  // choosing the one already chosen, or having no parent, just plays it (again).
  const choosePhase = useCallback(
    (phase) => {
      if (onSelectPhase && phase !== activePhase) onSelectPhase(phase);
      else playPhase(phase);
    },
    [onSelectPhase, activePhase, playPhase],
  );

  const gapSet = useMemo(() => new Set(ui.gaps ? ui.gaps.split(',') : []), [ui.gaps]);
  const cols = shown.length > 1 ? 'sm:grid-cols-2' : '';

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div className={cn('grid grid-cols-1 gap-2', cols)}>
        {shown.map((v) => (
          <Pane
            key={v.camera}
            camera={v.camera}
            label={v.label ?? v.camera}
            startIso={startIso}
            endIso={endIso}
            register={register}
            gap={gapSet.has(v.camera)}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          size="sm"
          onClick={togglePlay}
          aria-label={ui.playing ? 'Pause' : 'Play'}
        >
          {ui.playing ? <Pause className="size-4" /> : <Play className="size-4" />}
          {ui.playing ? 'Pause' : 'Play'}
        </Button>
        <input
          type="range"
          aria-label="Position"
          min={startMs}
          max={endMs}
          step={100}
          value={ui.masterMs}
          onChange={(e) => seek(Number(e.target.value))}
          className="min-w-40 flex-1 accent-accent"
        />
        <span className="text-sm tabular-nums text-text" aria-live="off">
          {formatClock(new Date(ui.masterMs))}
        </span>
        <span className="text-xs text-text-muted">
          {formatDateTime(new Date(startMs))} – {formatClock(new Date(endMs))}
        </span>
      </div>

      <CameraLanes
        lanes={shown.map((v) => ({ key: v.camera, label: v.label ?? v.camera }))}
        spans={spans}
        rangeStartMs={startMs}
        rangeEndMs={endMs}
        playheadMs={ui.masterMs}
        activePhase={activePhase}
        onSelectPhase={choosePhase}
        onScrub={seek}
      />

      {spans.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Play a phase">
          {spans.map((s) => (
            <li key={s.phase}>
              <Button
                type="button"
                size="sm"
                variant={activePhase === s.phase ? 'default' : 'outline'}
                aria-pressed={activePhase === s.phase}
                onClick={() => choosePhase(s.phase)}
              >
                {PHASE_LABEL[s.phase] ?? s.phase} · {formatClock(new Date(s.startMs))}
              </Button>
            </li>
          ))}
        </ul>
      )}

      <p
        data-testid="sync-status"
        data-playing={String(ui.playing)}
        data-playhead-ms={ui.masterMs}
        data-max-drift-ms={ui.maxDrift}
        data-drifts={ui.drifts ?? ''}
        data-corrections={ui.corrections ?? 0}
        data-samples={ui.samples ?? 0}
        className="text-xs text-text-muted"
      >
        {shown.length} camera{shown.length === 1 ? '' : 's'} on one playhead
        {ui.samples > 0 && ` · largest gap between pictures ${ui.maxDrift} ms`}
      </p>
    </div>
  );
}
