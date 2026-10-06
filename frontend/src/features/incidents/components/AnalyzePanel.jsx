import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { SeverityBadge } from '@/components/SeverityBadge';
import { errorMessage } from '@/lib/errorMessage';
import { useAnalyzeEvent, useEventReasoning } from '../api';

/** "Reasoning" section of the event page: ask for a phase-aware analysis of the incident this event
 * belongs to, follow it while it runs, and link to the finished report. Operators and admins.
 */
export function AnalyzePanel({ eventId, canAnalyze }) {
  const { data, isLoading } = useEventReasoning(eventId);
  const analyze = useAnalyzeEvent(eventId);
  const job = data?.job;
  const incident = data?.incident;
  const live = job?.status === 'queued' || job?.status === 'running';

  if (isLoading) return <p className="text-sm text-text-muted">Checking for a report…</p>;

  return (
    <div className="flex flex-col gap-2">
      {live && (
        <div role="status" className="flex flex-col gap-1 text-sm">
          <p className="text-text">
            {job.status === 'queued'
              ? `Waiting in the queue${job.queue_position ? `, position ${job.queue_position}` : ''}.`
              : `Analysing: ${job.stage}.`}
          </p>
          <div className="h-1.5 w-full overflow-hidden rounded-pill bg-surface-raised">
            <div
              className="h-full bg-accent transition-all"
              style={{ width: `${Math.round(Math.max(job.progress, 0.03) * 100)}%` }}
            />
          </div>
          <p className="text-xs text-text-muted">This can take a few minutes on the local GPU.</p>
        </div>
      )}

      {job?.status === 'failed' && !live && (
        <p role="alert" className="text-sm text-sev-critical">
          The last analysis failed: {job.error ?? 'unknown reason'}.
        </p>
      )}

      {incident && (
        <div className="flex flex-col gap-1 rounded-panel border border-rule p-3">
          <div className="flex items-center gap-2">
            <SeverityBadge severity={incident.severity} />
            <Link
              to={`/incidents/${incident.id}`}
              className="text-sm font-medium text-accent hover:underline"
            >
              {incident.title}
            </Link>
          </div>
          {incident.summary && <p className="text-sm text-text">{incident.summary}</p>}
        </div>
      )}

      {!incident && !live && job?.status !== 'failed' && (
        <p className="text-sm text-text-muted">No report has been written for this incident yet.</p>
      )}

      {canAnalyze ? (
        <Button
          size="sm"
          variant={incident ? 'outline' : 'default'}
          disabled={analyze.isPending || live}
          onClick={() => analyze.mutate()}
          className="self-start"
        >
          {incident ? 'Analyse again' : 'Analyse incident'}
        </Button>
      ) : (
        <p className="text-xs text-text-muted">Operators and admins can request an analysis.</p>
      )}
      {analyze.isError && (
        <p role="alert" className="text-sm text-sev-critical">
          {errorMessage(analyze.error, {
            forbidden: 'You do not have access to request an analysis.',
            fallback: 'Could not start the analysis. Try again.',
          })}
        </p>
      )}
    </div>
  );
}
