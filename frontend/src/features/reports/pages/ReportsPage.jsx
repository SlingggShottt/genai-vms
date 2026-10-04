import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useCurrentUser } from '@/features/auth/api';
import { ApiError } from '@/lib/apiClient';
import { formatDateTime } from '@/lib/time';
import { useReports, useRequestReport } from '../api';
import { STATUS_LABEL, periodLabel, shiftDay, siteToday } from '../lib';

function GenerateDialog({ open, onClose }) {
  const today = siteToday();
  const [from, setFrom] = useState(shiftDay(today, -1));
  const [to, setTo] = useState(shiftDay(today, -1));
  const request = useRequestReport();
  const message =
    request.error instanceof ApiError && request.error.status === 400
      ? request.error.message
      : request.isError
        ? 'Could not start the report. Check your connection and try again.'
        : null;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await request.mutateAsync({ date_from: from, date_to: to });
              onClose();
            } catch {
              // shown below
            }
          }}
          className="flex flex-col gap-4"
        >
          <DialogHeader>
            <DialogTitle>Generate report</DialogTitle>
            <DialogDescription>
              One report covers up to seven whole days, in site time (IST).
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-4">
            <div className="flex flex-1 flex-col gap-1">
              <Label htmlFor="report-from">From</Label>
              <Input
                id="report-from"
                type="date"
                value={from}
                max={today}
                onChange={(e) => setFrom(e.target.value)}
                required
              />
            </div>
            <div className="flex flex-1 flex-col gap-1">
              <Label htmlFor="report-to">To</Label>
              <Input
                id="report-to"
                type="date"
                value={to}
                max={today}
                onChange={(e) => setTo(e.target.value)}
                required
              />
            </div>
          </div>
          {message && (
            <p role="alert" className="text-sm text-sev-critical">
              {message}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={request.isPending}>
              Generate report
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Daily security reports (FR-RPT): the list, and a way to ask for one. A report is written by the
 * reasoning worker in the background; the list refreshes itself while any is still being written.
 */
export function ReportsPage() {
  const { data: user } = useCurrentUser();
  const canGenerate = user?.role === 'admin' || user?.role === 'operator';
  const { data, isLoading, isError } = useReports();
  const [open, setOpen] = useState(false);

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold text-text">Daily reports</h1>
          <p className="text-sm text-text-muted">
            What happened, by camera, type and hour, with the response times. A report is also
            written every morning for the day before.
          </p>
        </div>
        {canGenerate && (
          <Button className="ml-auto" onClick={() => setOpen(true)}>
            Generate report
          </Button>
        )}
      </header>

      {isLoading && <p className="text-sm text-text-muted">Loading reports…</p>}
      {isError && (
        <p role="alert" className="text-sm text-sev-critical">
          Could not load reports. Check your connection and try again.
        </p>
      )}
      {data && data.length === 0 && (
        <div className="rounded-panel border border-dashed border-rule p-6 text-sm text-text-muted">
          <p className="font-medium text-text">No reports yet</p>
          <p>Choose Generate report to write one for a day or a week.</p>
        </div>
      )}
      {data && data.length > 0 && (
        <ul className="flex flex-col divide-y divide-rule rounded-panel border border-rule bg-surface">
          {data.map((r) => (
            <li key={r.id}>
              <Link
                to={`/reports/${r.id}`}
                className="flex items-center gap-3 p-3 hover:bg-surface-raised"
              >
                <span className="font-medium text-text">{periodLabel(r)}</span>
                <span
                  className={
                    r.status === 'failed'
                      ? 'text-sm text-sev-critical'
                      : r.status === 'ready'
                        ? 'text-sm text-text-muted'
                        : 'text-sm text-accent'
                  }
                >
                  {STATUS_LABEL[r.status]}
                </span>
                <span className="ml-auto text-xs tabular-nums text-text-muted">
                  requested {formatDateTime(new Date(r.created_at))}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <GenerateDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
