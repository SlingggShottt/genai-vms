import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { useAlertsList } from '@/features/alerts/api';
import { canSeeAlerts } from '@/features/alerts/schemas';
import { useCurrentUser } from '@/features/auth/api';
import { useCameras } from '@/features/cameras/api';
import { EventFilters } from '../components/EventFilters';
import { EventsTable } from '../components/EventsTable';
import { apiFilters, filtersFromSearch, hasFilters, searchFromFilters } from '../filters';

/** Events that raised an alert, newest first, filterable by status, severity, camera and time
 * (FR-ALR-02). The filters live in the URL. New and changed alerts arrive over the live channel
 * (the app shell's `LiveAlertsProvider` refetches this list), so it stays current while open.
 *
 * Source: `GET /alerts`. `GET /events` (every verified event, including those below the alert
 * threshold) arrives with P3-D4's `events.events` table; this page then switches its source.
 */
export function EventsPage() {
  const { data: user } = useCurrentUser();
  const allowed = canSeeAlerts(user);
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = filtersFromSearch(searchParams);
  const { data: cameras } = useCameras();
  const query = useAlertsList(apiFilters(filters), { enabled: allowed });

  const alerts = query.data?.pages.flatMap((page) => page.items) ?? [];

  if (!allowed) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-text-muted">
        <p>Events are shown to operators and admins.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-text">Events</h1>
        <p className="text-sm text-text-muted">Events that raised an alert, newest first.</p>
      </div>

      <EventFilters
        filters={filters}
        cameras={cameras?.items ?? []}
        onChange={(next) => setSearchParams(searchFromFilters(next), { replace: true })}
      />

      {query.isLoading && <p className="text-sm text-text-muted">Loading events…</p>}

      {query.isError && (
        <div className="flex flex-col items-start gap-2 text-sm text-text-muted">
          <p>Could not load events. Check your connection and try again.</p>
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            Try again
          </Button>
        </div>
      )}

      {query.data && alerts.length === 0 && (
        <p className="text-sm text-text-muted">
          {hasFilters(filters)
            ? 'No events match these filters. Clear the filters to see every event that raised an alert.'
            : 'No events yet. Events that raise an alert appear here once they are detected.'}
        </p>
      )}

      {alerts.length > 0 && (
        <>
          <EventsTable alerts={alerts} />
          <div className="flex items-center gap-3 text-sm text-text-muted">
            <span className="tabular-nums">
              {alerts.length} {alerts.length === 1 ? 'event' : 'events'} shown
            </span>
            {query.hasNextPage && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => query.fetchNextPage()}
                disabled={query.isFetchingNextPage}
              >
                {query.isFetchingNextPage ? 'Loading…' : 'Show more'}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
