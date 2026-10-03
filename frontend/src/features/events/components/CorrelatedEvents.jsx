import { SeverityBadge } from '@/components/SeverityBadge';
import { useCorrelationGroup } from '@/features/alerts/api';
import { eventTypeLabel } from '@/lib/eventTypes';
import { formatDateTime } from '@/lib/time';
import { describeLink } from '../lib';

/** The other events correlation linked to this one — across cameras, by the camera graph and by
 * time (design §7.5) — and why. Members are listed by when they started.
 *
 * @param {{alert: {event_id: string, group: {id: string, event_count: number}|null}}} props
 */
export function CorrelatedEvents({ alert }) {
  const groupId = alert.group && alert.group.event_count > 1 ? alert.group.id : null;
  const { data: group, isLoading, isError } = useCorrelationGroup(groupId);

  if (!groupId) {
    return <p className="text-sm text-text-muted">Not linked with any other event.</p>;
  }
  if (isLoading) return <p className="text-sm text-text-muted">Loading correlated events…</p>;
  if (isError || !group) {
    return (
      <p className="text-sm text-text-muted">
        Could not load the correlated events. Reload the page to try again.
      </p>
    );
  }

  const members = [...group.members].sort((a, b) => a.start_ts.localeCompare(b.start_ts));
  const byEvent = new Map(members.map((m) => [m.event_id, m]));

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-text-muted">
        {members.length} events on {group.camera_ids.join(', ')}
        {group.status === 'open' && ', still being grouped'}
      </p>

      <ul className="flex flex-col">
        {members.map((member) => {
          const isThis = member.event_id === alert.event_id;
          return (
            <li
              key={member.event_id}
              data-event-id={member.event_id}
              aria-current={isThis ? 'true' : undefined}
              className="flex flex-wrap items-center gap-2 border-b border-rule py-2 text-sm"
            >
              <SeverityBadge severity={member.severity} />
              <span className="font-medium text-text">{eventTypeLabel(member.event_type)}</span>
              <span className="font-condensed text-text-muted">{member.camera_id}</span>
              <time dateTime={member.start_ts} className="tabular-nums text-text-muted">
                {formatDateTime(new Date(member.start_ts))}
              </time>
              {isThis && <span className="text-xs text-accent">This event</span>}
            </li>
          );
        })}
      </ul>

      {group.links.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium text-text">Why they were linked</h3>
          <ul className="flex flex-col gap-1 text-sm text-text-muted">
            {group.links.map((link) => (
              <li key={`${link.from_event}-${link.to_event}`}>{describeLink(link, byEvent)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
