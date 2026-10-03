import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useCurrentUser } from '@/features/auth/api';
import { useNow } from '@/lib/useNow';
import { cn } from '@/lib/utils';
import { useTrayAlerts } from '../api';
import { useLiveAlerts } from '../LiveAlerts';
import { canSeeAlerts } from '../schemas';
import { AlertItem } from './AlertItem';
import { AlertNoteDialog } from './AlertNoteDialog';

const STATUS_TEXT = {
  connecting: 'Connecting to live updates…',
  reconnecting: 'Live updates paused. Reconnecting…',
  offline: 'Live updates are off. Sign in again to resume.',
};

/** The collapsible alert tray (§B.5, §B.7). Operators and admins see alerts; a viewer is told
 * who does. The two screen-reader regions are always mounted, even when the tray is collapsed:
 * new alerts are announced politely, critical ones assertively (§B.10).
 */
export function AlertTray({ open, onToggle }) {
  const { data: user } = useCurrentUser();
  const allowed = canSeeAlerts(user);
  const { data, isLoading, isError, refetch } = useTrayAlerts({ enabled: allowed });
  const live = useLiveAlerts();
  const now = useNow();
  const [pending, setPending] = useState({ action: null, alert: null });

  const items = data?.items ?? [];
  const openCount = items.filter((a) => a.status === 'open').length;

  return (
    <aside
      aria-label="Alerts"
      className={cn(
        'flex flex-col border-l border-rule bg-surface transition-[width]',
        open ? 'w-alert-tray' : 'w-10',
      )}
    >
      <div className="sr-only">
        <div role="status" aria-live="polite" aria-atomic="true">
          {live.polite && <span key={live.polite.sequence}>{live.polite.text}</span>}
        </div>
        <div role="alert" aria-live="assertive" aria-atomic="true">
          {live.assertive && <span key={live.assertive.sequence}>{live.assertive.text}</span>}
        </div>
      </div>

      <div className="flex h-14 items-center justify-between border-b border-rule px-3">
        {open && (
          <span className="flex items-center gap-2 text-sm font-medium text-text">
            Alerts
            {allowed && openCount > 0 && (
              <span className="rounded-pill bg-surface-raised px-2 text-xs tabular-nums text-text-muted">
                {openCount} open
              </span>
            )}
          </span>
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? 'Collapse alert tray' : 'Expand alert tray'}
          className="relative flex h-8 w-8 items-center justify-center rounded-panel text-text-muted hover:bg-surface-raised hover:text-text"
        >
          {open ? (
            <ChevronRight size={16} className="rotate-180" aria-hidden="true" />
          ) : (
            <Bell size={16} aria-hidden="true" />
          )}
          {!open && allowed && openCount > 0 && (
            <span className="absolute -right-1 -top-1 rounded-pill bg-sev-high px-1 text-xs tabular-nums text-accent-ink">
              {openCount}
            </span>
          )}
        </button>
      </div>

      {open && (
        <div className="flex min-h-0 flex-1 flex-col">
          {!allowed ? (
            <p className="p-4 text-center text-sm text-text-muted">
              Alerts are shown to operators and admins.
            </p>
          ) : (
            <>
              {STATUS_TEXT[live.status] && (
                <p className="border-b border-rule px-3 py-2 text-xs text-text-muted">
                  {STATUS_TEXT[live.status]}
                </p>
              )}
              {isLoading && (
                <p className="p-4 text-center text-sm text-text-muted">Loading alerts…</p>
              )}
              {isError && (
                <div className="flex flex-col items-center gap-2 p-4 text-center text-sm text-text-muted">
                  <p>Could not load alerts. Check your connection and try again.</p>
                  <Button size="sm" variant="outline" onClick={() => refetch()}>
                    Try again
                  </Button>
                </div>
              )}
              {data && items.length === 0 && (
                <p className="p-4 text-center text-sm text-text-muted">
                  No open alerts. New alerts appear here as events are detected.
                </p>
              )}
              {items.length > 0 && (
                <ul className="flex-1 overflow-y-auto">
                  {items.map((alert) => (
                    <AlertItem
                      key={alert.id}
                      alert={alert}
                      now={now}
                      isNew={live.freshIds.has(alert.id)}
                      onAct={(action, target) => setPending({ action, alert: target })}
                    />
                  ))}
                </ul>
              )}
              <div className="border-t border-rule p-3">
                <Link to="/events" className="text-sm text-accent hover:underline">
                  All events
                </Link>
              </div>
            </>
          )}
        </div>
      )}

      <AlertNoteDialog
        action={pending.action}
        alert={pending.alert}
        onClose={() => setPending({ action: null, alert: null })}
      />
    </aside>
  );
}
