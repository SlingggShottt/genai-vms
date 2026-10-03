import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { SEVERITY_META, SeverityBadge } from '@/components/SeverityBadge';
import { formatAbsolute, formatRelative } from '@/lib/time';
import { cn } from '@/lib/utils';
import { shouldPulse } from '../liveCache';

/** One alert in the tray (§B.7): a 3 px severity bar, title, camera, relative + absolute time,
 * and the actions *Acknowledge* / *Resolve* / *Open*. A new high or critical alert pulses once.
 *
 * @param {object} props
 * @param {import('../schemas').Alert} props.alert
 * @param {Date} props.now  shared clock, so "2 min ago" keeps counting without a timer per row
 * @param {boolean} [props.isNew]  arrived over the live channel moments ago
 * @param {(action: 'acknowledge'|'resolve', alert: object) => void} props.onAct
 */
export function AlertItem({ alert, now, isNew = false, onAct }) {
  const when = new Date(alert.start_ts);
  const others = alert.group ? alert.group.event_count - 1 : 0;
  const pulse = isNew && shouldPulse(alert) ? `alert-pulse-${alert.severity}` : '';

  return (
    <li
      data-alert-id={alert.id}
      data-new={isNew ? 'true' : undefined}
      className={cn(
        'flex flex-col gap-2 border-b border-l-3 border-rule p-3',
        SEVERITY_META[alert.severity].bar,
        pulse,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-text">{alert.title}</span>
        <SeverityBadge severity={alert.severity} className="shrink-0" />
      </div>

      <p className="text-xs text-text-muted">
        <span className="font-condensed">{alert.camera_code}</span>
        {' · '}
        <time dateTime={alert.start_ts} className="tabular-nums">
          {formatRelative(when, now)}, {formatAbsolute(when, now)}
        </time>
      </p>

      {others > 0 && (
        <p className="text-xs text-text-muted">
          Linked with {others} other {others === 1 ? 'event' : 'events'} on{' '}
          {alert.group.camera_ids.join(', ')}
        </p>
      )}

      {alert.status === 'acknowledged' && (
        <p className="text-xs text-text-muted">
          Acknowledged{alert.ack_note ? `: ${alert.ack_note}` : ''}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {alert.status === 'open' && (
          <Button size="sm" onClick={() => onAct('acknowledge', alert)}>
            Acknowledge
          </Button>
        )}
        {alert.status !== 'resolved' && (
          <Button size="sm" variant="outline" onClick={() => onAct('resolve', alert)}>
            Resolve
          </Button>
        )}
        <Button size="sm" variant="ghost" asChild>
          <Link to={`/events/${alert.id}`}>Open</Link>
        </Button>
      </div>
    </li>
  );
}
