import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { SeverityBadge } from '@/components/SeverityBadge';
import { Button } from '@/components/ui/button';
import { alertForEvent } from '@/features/assistant/api';
import { AddToCaseDialog } from '@/features/cases/components/AddToCaseDialog';
import { useCurrentUser } from '@/features/auth/api';
import { eventTypeLabel } from '@/lib/eventTypes';
import { formatClock, formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useTimeline } from '../api';
import { PRESETS, pct, selectionRange, span, ticks } from '../lib';

const SEV_FILL = {
  low: 'bg-sev-low',
  medium: 'bg-sev-medium',
  high: 'bg-sev-high',
  critical: 'bg-sev-critical',
};

function Lane({ camera, view, data, selection, onSelect, onPick }) {
  const track = useRef(null);
  const drag = useRef(null);
  const { start, end } = view;

  const fraction = (clientX) => {
    const box = track.current.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - box.left) / box.width));
  };

  const events = data.events.filter((e) => e.camera_id === camera);
  const incidents = data.incidents.filter((i) => i.camera_ids.includes(camera));
  const mine = selection?.camera === camera ? selection : null;

  return (
    <div className="grid grid-cols-[5rem_1fr] items-stretch gap-2">
      <div className="flex items-center font-condensed text-sm text-text">{camera}</div>
      <div
        ref={track}
        role="group"
        aria-label={`Timeline of ${camera}`}
        className="relative h-16 touch-none rounded-panel border border-rule bg-surface"
        onPointerDown={(e) => {
          if (e.target !== track.current) return; // markers handle their own presses
          track.current.setPointerCapture?.(e.pointerId);
          drag.current = fraction(e.clientX);
          onSelect(null);
        }}
        onPointerMove={(e) => {
          if (drag.current == null) return;
          const range = selectionRange(drag.current, fraction(e.clientX), start, end);
          onSelect({ camera, ...range, dragging: true });
        }}
        onPointerUp={(e) => {
          if (drag.current == null) return;
          const range = selectionRange(drag.current, fraction(e.clientX), start, end);
          drag.current = null;
          // A click without a drag selects nothing.
          onSelect(range.end - range.start < (end - start) * 0.005 ? null : { camera, ...range });
        }}
      >
        {mine && (
          <div
            className="pointer-events-none absolute inset-y-0 bg-accent-tint ring-1 ring-accent"
            style={{
              left: `${pct(mine.start, start, end)}%`,
              width: `${pct(mine.end, start, end) - pct(mine.start, start, end)}%`,
            }}
          />
        )}
        {incidents.map((i) => {
          const s = span(i.start, i.end, start, end, 0.6);
          return (
            <button
              key={i.id}
              type="button"
              aria-label={`Incident report: ${i.title}`}
              title={i.title}
              onClick={() => onPick({ type: 'incident', item: i })}
              className={cn('absolute bottom-1 h-2 rounded-pill opacity-80', SEV_FILL[i.severity])}
              style={{ left: `${s.left}%`, width: `${s.width}%` }}
            />
          );
        })}
        {events.map((e) => {
          const s = span(e.start, e.end, start, end, 0.5);
          return (
            <button
              key={e.id}
              type="button"
              aria-label={`${eventTypeLabel(e.event_type)} event at ${formatClock(new Date(e.start))}`}
              title={`${eventTypeLabel(e.event_type)} · ${formatClock(new Date(e.start))}`}
              onClick={() => onPick({ type: 'event', item: e })}
              className={cn(
                'absolute top-2 h-5 min-w-[6px] rounded-tile ring-1 ring-surface',
                SEV_FILL[e.severity],
              )}
              style={{ left: `${s.left}%`, width: `${s.width}%` }}
            />
          );
        })}
      </div>
    </div>
  );
}

/** The investigation timeline (FR-INV): every camera's verified events and incident reports on
 * one time axis. Drag on a lane to select a period, then zoom to it, open the recording, or save
 * it to a case; press a marker to see what it is.
 */
export function TimelinePage() {
  const navigate = useNavigate();
  const { data: user } = useCurrentUser();
  const canSave = user?.role === 'admin' || user?.role === 'operator';
  const [presetValue, setPreset] = useState('6h');
  const [custom, setCustom] = useState(null); // {start, end} ms after a zoom
  const [anchor, setAnchor] = useState(() => Date.now());
  const [selection, setSelection] = useState(null);
  const [picked, setPicked] = useState(null);
  const [saving, setSaving] = useState(null);

  const view = useMemo(() => {
    if (custom) return custom;
    const preset = PRESETS.find((p) => p.value === presetValue);
    return { start: anchor - preset.ms, end: anchor };
  }, [custom, presetValue, anchor]);

  const { data, isLoading, isError } = useTimeline(
    new Date(view.start).toISOString(),
    new Date(view.end).toISOString(),
  );
  const axis = ticks(view.start, view.end);
  const multi = view.end - view.start > 24 * 3600e3;

  function choose(value) {
    setPreset(value);
    setCustom(null);
    setAnchor(Date.now());
    setSelection(null);
    setPicked(null);
  }

  async function openEvent(event) {
    if (event.alert_id) return navigate(`/events/${event.alert_id}`);
    try {
      const alertId = await alertForEvent(event.id);
      if (alertId) navigate(`/events/${alertId}`);
      else toast('This event raised no alert, so it has no page of its own.');
    } catch {
      toast('Could not open the event. Try again.');
    }
    return undefined;
  }

  const playbackHref = selection
    ? `/playback?${new URLSearchParams({
        camera: selection.camera,
        start: new Date(selection.start).toISOString(),
        end: new Date(selection.end).toISOString(),
      }).toString()}`
    : null;

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold text-text">Timeline</h1>
          <p className="text-sm text-text-muted">
            Drag across a camera’s lane to pick a period; press a marker to see what happened.
          </p>
        </div>
        <label className="ml-auto flex items-center gap-2 text-sm text-text-muted">
          Period
          <select
            value={custom ? 'custom' : presetValue}
            onChange={(e) => choose(e.target.value)}
            className="h-9 rounded-panel border border-rule bg-surface px-2 text-sm text-text"
          >
            {custom && <option value="custom">Zoomed selection</option>}
            {PRESETS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <Button size="sm" variant="outline" onClick={() => choose(custom ? '6h' : presetValue)}>
          {custom ? 'Reset zoom' : 'Refresh'}
        </Button>
      </header>

      {isLoading && <p className="text-sm text-text-muted">Loading the timeline…</p>}
      {isError && (
        <p role="alert" className="text-sm text-sev-critical">
          Could not load the timeline. Check your connection and try again.
        </p>
      )}

      {data && (
        <section className="flex flex-col gap-2" aria-label="Cameras">
          <div className="grid grid-cols-[5rem_1fr] gap-2" aria-hidden="true">
            <span />
            <div className="relative h-5 text-xs tabular-nums text-text-muted">
              {axis.map((t) => (
                <span
                  key={t}
                  className="absolute -translate-x-1/2"
                  style={{ left: `${pct(t, view.start, view.end)}%` }}
                >
                  {multi ? formatDateTime(new Date(t)) : formatClock(new Date(t)).slice(0, 5)}
                </span>
              ))}
            </div>
          </div>
          {data.cameras.length === 0 && (
            <p className="rounded-panel border border-dashed border-rule p-4 text-sm text-text-muted">
              No camera recorded anything in this period. Try a longer one.
            </p>
          )}
          {data.cameras.map((camera) => (
            <Lane
              key={camera}
              camera={camera}
              view={view}
              data={data}
              selection={selection}
              onSelect={setSelection}
              onPick={setPicked}
            />
          ))}
          {data.groups.length > 0 && (
            <p className="text-xs text-text-muted">
              {data.groups.length} group{data.groups.length === 1 ? '' : 's'} of events linked
              across cameras in this period.
            </p>
          )}
          <p className="text-xs text-text-muted">
            Bars above are events, thin bars below are incident reports; colour and the marker title
            give the severity.
          </p>
        </section>
      )}

      {selection && !selection.dragging && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 rounded-panel border border-accent bg-accent-tint p-3 text-sm"
        >
          <span className="tabular-nums text-text">
            {selection.camera} · {formatClock(new Date(selection.start))} to{' '}
            {formatClock(new Date(selection.end))}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setCustom({ start: selection.start, end: selection.end });
              setSelection(null);
            }}
          >
            Zoom to selection
          </Button>
          {playbackHref && (
            <Button size="sm" variant="outline" asChild>
              <Link to={playbackHref}>Open recording</Link>
            </Button>
          )}
          {canSave && (
            <Button
              size="sm"
              onClick={() =>
                setSaving({
                  kind: 'footage',
                  label: `${selection.camera} ${formatClock(new Date(selection.start))}–${formatClock(new Date(selection.end))}`,
                  camera_id: selection.camera,
                  ts_start: new Date(selection.start).toISOString(),
                  ts_end: new Date(selection.end).toISOString(),
                })
              }
            >
              Save to case
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setSelection(null)}>
            Clear
          </Button>
        </div>
      )}

      {picked && (
        <aside
          aria-label="Selected marker"
          className="flex flex-col gap-2 rounded-panel border border-rule bg-surface p-3 text-sm"
        >
          {picked.type === 'event' ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={picked.item.severity} />
                <strong className="font-medium text-text">
                  {eventTypeLabel(picked.item.event_type)} on {picked.item.camera_id}
                </strong>
                <span className="tabular-nums text-text-muted">
                  {formatDateTime(new Date(picked.item.start))}
                </span>
              </div>
              {picked.item.caption && <p className="text-text">{picked.item.caption}</p>}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => openEvent(picked.item)}>
                  Open event
                </Button>
                {canSave && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setSaving({
                        kind: 'event',
                        label: `${eventTypeLabel(picked.item.event_type)} on ${picked.item.camera_id}, ${formatClock(new Date(picked.item.start))}`,
                        ref: picked.item.id,
                        camera_id: picked.item.camera_id,
                        ts_start: picked.item.start,
                        ts_end: picked.item.end,
                      })
                    }
                  >
                    Save to case
                  </Button>
                )}
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={picked.item.severity} />
                <strong className="font-medium text-text">{picked.item.title}</strong>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" asChild>
                  <Link to={`/incidents/${picked.item.id}`}>Open report</Link>
                </Button>
                {canSave && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setSaving({
                        kind: 'incident',
                        label: picked.item.title,
                        ref: picked.item.id,
                        camera_id: picked.item.camera_ids[0],
                        ts_start: picked.item.start,
                        ts_end: picked.item.end,
                      })
                    }
                  >
                    Save to case
                  </Button>
                )}
              </div>
            </>
          )}
        </aside>
      )}

      <AddToCaseDialog item={saving} onClose={() => setSaving(null)} />
    </div>
  );
}
