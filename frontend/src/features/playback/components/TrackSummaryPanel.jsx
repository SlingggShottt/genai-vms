import { Button } from '@/components/ui/button';
import { formatClock } from '@/lib/time';
import { useTrackSummary } from '../api';

const ATTRIBUTE_LABELS = {
  upper_color: 'Upper colour',
  lower_color: 'Lower colour',
  color: 'Colour',
};

/** Side panel for a clicked overlay box (P2-J6 AC: "click a box -> side
 * panel with track summary (attributes, dwell, zones)"). `trackId` is
 * `null` when nothing is selected, in which case the panel isn't rendered.
 */
export function TrackSummaryPanel({ trackId, onClose }) {
  const { data: track, isLoading, isError } = useTrackSummary(trackId);

  if (!trackId) return null;

  return (
    <div className="flex w-full max-w-xs shrink-0 flex-col gap-3 rounded-panel border border-rule bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-text-muted">Track</p>
          <p className="font-mono text-sm text-text">{trackId}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close track details">
          ×
        </Button>
      </div>

      {isLoading && <p className="text-sm text-text-muted">Loading…</p>}
      {isError && <p className="text-sm text-sev-high">Could not load this track.</p>}

      {track && (
        <dl className="flex flex-col gap-3 text-sm">
          <div>
            <dt className="text-xs text-text-muted">Category</dt>
            <dd className="capitalize text-text">{track.category}</dd>
          </div>

          <div>
            <dt className="text-xs text-text-muted">Dwell time</dt>
            <dd className="text-text">{track.dwell_s.toFixed(1)}s</dd>
          </div>

          <div>
            <dt className="text-xs text-text-muted">First / last seen</dt>
            <dd className="text-text">
              {formatClock(new Date(track.first_ts))} – {formatClock(new Date(track.last_ts))}
            </dd>
          </div>

          <div>
            <dt className="text-xs text-text-muted">Zones visited</dt>
            <dd className="text-text">
              {track.zones_visited.length > 0 ? track.zones_visited.join(', ') : '—'}
            </dd>
          </div>

          {Object.keys(track.attributes_summary).length > 0 && (
            <div>
              <dt className="text-xs text-text-muted">Attributes</dt>
              <dd className="flex flex-col gap-0.5 text-text">
                {Object.entries(track.attributes_summary).map(([key, value]) => (
                  <span key={key}>
                    {ATTRIBUTE_LABELS[key] ?? key}: {value}
                  </span>
                ))}
              </dd>
            </div>
          )}
        </dl>
      )}
    </div>
  );
}
