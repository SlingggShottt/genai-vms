import { Link } from 'react-router-dom';
import { SeverityBadge } from '@/components/SeverityBadge';
import { formatDateTime } from '@/lib/time';

const STATUS_LABEL = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved' };

/** Dense table, aligned numbers rather than boxes (§B.2 principle 4). The title is the link:
 * keyboard and screen-reader users get the same way in as everyone.
 *
 * @param {{alerts: import('@/features/alerts/schemas').Alert[]}} props
 */
export function EventsTable({ alerts }) {
  return (
    <table className="w-full border-collapse text-left text-sm">
      <thead>
        <tr className="border-b border-rule text-text-muted">
          <th scope="col" className="py-2 pr-4 font-medium">
            Time
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Severity
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Event
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Camera
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Status
          </th>
          <th scope="col" className="py-2 font-medium">
            Linked events
          </th>
        </tr>
      </thead>
      <tbody>
        {alerts.map((alert) => {
          const others = alert.group ? alert.group.event_count - 1 : 0;
          return (
            <tr key={alert.id} data-alert-id={alert.id} className="border-b border-rule">
              <td className="py-2 pr-4 tabular-nums text-text-muted">
                <time dateTime={alert.start_ts}>{formatDateTime(new Date(alert.start_ts))}</time>
              </td>
              <td className="py-2 pr-4">
                <SeverityBadge severity={alert.severity} />
              </td>
              <td className="py-2 pr-4">
                <Link to={`/events/${alert.id}`} className="text-accent hover:underline">
                  {alert.title}
                </Link>
              </td>
              <td className="py-2 pr-4 font-condensed">{alert.camera_code}</td>
              <td className="py-2 pr-4">{STATUS_LABEL[alert.status]}</td>
              <td className="py-2 tabular-nums text-text-muted">{others > 0 ? others : 'None'}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
