import { useState } from 'react';
import { Link } from 'react-router-dom';
import { SeverityBadge } from '@/components/SeverityBadge';
import { eventTypeLabel } from '@/lib/eventTypes';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useIncidents } from '../api';
import { STATUS_LABEL } from '../lib';

const SEVERITIES = ['critical', 'high', 'medium', 'low'];

/** Incident reports (FR-INC): what the system worked out about each serious event, newest first. */
export function IncidentsPage() {
  const [severity, setSeverity] = useState([]);
  // A report that failed (a worker stopped mid-way, the footage had expired) is not an incident
  // an operator can act on; it stays visible on the event's own page.
  const { data, isLoading, isError } = useIncidents({
    severity,
    status: ['generating', 'generated', 'reviewed', 'closed'],
  });

  function toggle(level) {
    setSeverity((prev) =>
      prev.includes(level) ? prev.filter((s) => s !== level) : [...prev, level],
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-text">Incidents</h1>
        <p className="text-sm text-text-muted">
          Reports written from the footage: what happened, in which phases, and why. Open an event
          and choose Analyse incident to write one.
        </p>
      </header>

      <div role="group" aria-label="Severity" className="flex flex-wrap gap-2">
        {SEVERITIES.map((level) => (
          <button
            key={level}
            type="button"
            aria-pressed={severity.includes(level)}
            onClick={() => toggle(level)}
            className={cn(
              'rounded-pill border px-3 py-1 text-sm capitalize',
              severity.includes(level)
                ? 'border-accent bg-accent-tint text-accent'
                : 'border-rule text-text-muted hover:text-text',
            )}
          >
            {level}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-sm text-text-muted">Loading incidents…</p>}
      {isError && (
        <p role="alert" className="text-sm text-sev-critical">
          Could not load incidents. Check your connection and try again.
        </p>
      )}
      {data && data.items.length === 0 && (
        <div className="rounded-panel border border-dashed border-rule p-6 text-sm text-text-muted">
          <p className="font-medium text-text">No incident reports yet</p>
          <p>
            Reports are written automatically for serious correlated events, or on request from an
            event page.
          </p>
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="flex flex-col divide-y divide-rule rounded-panel border border-rule bg-surface">
          {data.items.map((i) => (
            <li key={i.id}>
              <Link
                to={`/incidents/${i.id}`}
                className="flex flex-col gap-1 p-3 hover:bg-surface-raised"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={i.severity} />
                  <span className="font-medium text-text">{i.title}</span>
                  <span className="ml-auto text-xs text-text-muted">
                    {STATUS_LABEL[i.status] ?? i.status}
                  </span>
                </div>
                {i.summary && <p className="line-clamp-2 text-sm text-text-muted">{i.summary}</p>}
                <p className="text-xs tabular-nums text-text-muted">
                  {eventTypeLabel(i.event_type)} · {i.camera_ids.join(', ')} ·{' '}
                  {formatDateTime(new Date(i.window_start))}
                  {i.confidence != null && ` · confidence ${Math.round(i.confidence * 100)}%`}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
