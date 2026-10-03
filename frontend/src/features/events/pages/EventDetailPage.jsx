import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { SeverityBadge } from '@/components/SeverityBadge';
import { Button } from '@/components/ui/button';
import { useAlert } from '@/features/alerts/api';
import { AlertNoteDialog } from '@/features/alerts/components/AlertNoteDialog';
import { canSeeAlerts } from '@/features/alerts/schemas';
import { useCurrentUser } from '@/features/auth/api';
import { ApiError } from '@/lib/apiClient';
import { formatClock, formatDateTime } from '@/lib/time';
import { ClipPlayer } from '../components/ClipPlayer';
import { CorrelatedEvents } from '../components/CorrelatedEvents';
import { KeyframeStrip } from '../components/KeyframeStrip';
import { clipRange, verificationNote } from '../lib';

const STATUS_LABEL = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved' };

function Section({ title, children }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold text-text">{title}</h2>
      {children}
    </section>
  );
}

function Detail({ label, children }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 text-text-muted">{label}</dt>
      <dd className="min-w-0 text-text">{children}</dd>
    </div>
  );
}

/** One event: its clip, keyframes, the vision model's description (with how sure it was), the
 * facts, and the other events correlation linked to it. Acknowledge and resolve work here as
 * in the tray.
 */
export function EventDetailPage() {
  const { alertId } = useParams();
  const { data: user } = useCurrentUser();
  const allowed = canSeeAlerts(user);
  const { data: alert, isLoading, isError, error } = useAlert(alertId, { enabled: allowed });
  const [pending, setPending] = useState({ action: null, alert: null });

  if (!allowed) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-text-muted">
        <p>Events are shown to operators and admins.</p>
      </div>
    );
  }
  if (isLoading) return <p className="p-4 text-sm text-text-muted">Loading event…</p>;
  if (isError || !alert) {
    const missing = error instanceof ApiError && (error.status === 404 || error.status === 400);
    return (
      <div className="flex flex-col items-start gap-2 p-4 text-sm text-text-muted">
        <p>
          {missing
            ? 'This event was not found. It may have been removed.'
            : 'Could not load this event. Check your connection and try again.'}
        </p>
        <Link to="/events" className="text-accent hover:underline">
          All events
        </Link>
      </div>
    );
  }

  const start = new Date(alert.start_ts);
  const end = new Date(alert.end_ts);
  const clip = clipRange(alert);
  const verification = verificationNote(alert);

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <Link to="/events" className="text-sm text-accent hover:underline">
        All events
      </Link>

      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-text">{alert.title}</h1>
        <SeverityBadge severity={alert.severity} />
        <span className="text-sm text-text-muted">{STATUS_LABEL[alert.status]}</span>
        <div className="ml-auto flex gap-2">
          {alert.status === 'open' && (
            <Button size="sm" onClick={() => setPending({ action: 'acknowledge', alert })}>
              Acknowledge
            </Button>
          )}
          {alert.status !== 'resolved' && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPending({ action: 'resolve', alert })}
            >
              Resolve
            </Button>
          )}
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <Section title="Clip">
            <ClipPlayer
              cameraCode={alert.camera_code}
              startIso={clip.startIso}
              endIso={clip.endIso}
            />
            <p className="text-xs text-text-muted">10 seconds before and after the event.</p>
          </Section>
          <Section title="Keyframes">
            <KeyframeStrip
              urls={alert.keyframe_urls}
              count={alert.keyframe_count}
              camera={alert.camera_code}
            />
          </Section>
        </div>

        <div className="flex flex-col gap-4">
          <Section title="Description">
            {alert.caption ? (
              <p className="text-sm text-text">{alert.caption}</p>
            ) : (
              <p className="text-sm text-text-muted">
                No description was generated for this event.
              </p>
            )}
            <p className="text-xs text-text-muted">{verification.text}</p>
            {verification.low && (
              <p className="text-sm font-medium text-text">
                Low confidence — review the clip before acting.
              </p>
            )}
          </Section>

          <Section title="Details">
            <dl className="flex flex-col gap-1 text-sm">
              <Detail label="Camera">
                <span className="font-condensed">{alert.camera_code}</span>
              </Detail>
              <Detail label="When">
                <span className="tabular-nums">
                  {formatDateTime(start)} to {formatClock(end)}
                </span>
              </Detail>
              <Detail label="Rule">{alert.rule_id}</Detail>
              <Detail label="Zone">{alert.zone_id ?? 'Whole camera'}</Detail>
              {alert.acknowledged_at && (
                <Detail label="Acknowledged">
                  <span className="tabular-nums">
                    {formatDateTime(new Date(alert.acknowledged_at))}
                  </span>
                  {alert.ack_note ? `, ${alert.ack_note}` : ''}
                </Detail>
              )}
              {alert.resolved_at && (
                <Detail label="Resolved">
                  <span className="tabular-nums">
                    {formatDateTime(new Date(alert.resolved_at))}
                  </span>
                  {alert.resolve_note ? `, ${alert.resolve_note}` : ''}
                </Detail>
              )}
            </dl>
          </Section>

          <Section title="Correlated events">
            <CorrelatedEvents alert={alert} />
          </Section>
        </div>
      </div>

      <AlertNoteDialog
        action={pending.action}
        alert={pending.alert}
        onClose={() => setPending({ action: null, alert: null })}
      />
    </div>
  );
}
