import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { ALERT_STATUSES, SEVERITIES } from '@/features/alerts/schemas';
import { EMPTY_FILTERS, hasFilters, rangeError } from '../filters';

const STATUS_LABEL = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved' };
const SEVERITY_LABEL = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };

const FIELD =
  'h-9 rounded-panel border border-rule bg-surface px-3 text-sm text-text disabled:opacity-50';

/**
 * @param {object} props
 * @param {import('../filters').Filters} props.filters
 * @param {(next: import('../filters').Filters) => void} props.onChange  called on every change
 * @param {{code: string, name: string}[]} props.cameras
 */
export function EventFilters({ filters, onChange, cameras }) {
  const set = (name) => (event) => onChange({ ...filters, [name]: event.target.value });
  const error = rangeError(filters);

  return (
    <form
      aria-label="Filter events"
      onSubmit={(event) => event.preventDefault()}
      className="flex flex-wrap items-end gap-3"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="events-status">Status</Label>
        <select
          id="events-status"
          value={filters.status}
          onChange={set('status')}
          className={FIELD}
        >
          <option value="">All statuses</option>
          {ALERT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="events-severity">Severity</Label>
        <select
          id="events-severity"
          value={filters.severity}
          onChange={set('severity')}
          className={FIELD}
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABEL[s]}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="events-camera">Camera</Label>
        <select
          id="events-camera"
          value={filters.camera}
          onChange={set('camera')}
          className={FIELD}
        >
          <option value="">All cameras</option>
          {cameras.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="events-from">From</Label>
        <input
          id="events-from"
          type="datetime-local"
          value={filters.from}
          onChange={set('from')}
          aria-invalid={Boolean(error)}
          className={FIELD}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="events-to">To</Label>
        <input
          id="events-to"
          type="datetime-local"
          value={filters.to}
          onChange={set('to')}
          aria-invalid={Boolean(error)}
          className={FIELD}
        />
      </div>

      <Button
        type="button"
        variant="ghost"
        onClick={() => onChange(EMPTY_FILTERS)}
        disabled={!hasFilters(filters)}
      >
        Clear filters
      </Button>

      {error && (
        <p role="alert" className="basis-full text-sm text-sev-critical">
          {error}
        </p>
      )}
    </form>
  );
}
