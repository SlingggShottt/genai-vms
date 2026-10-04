import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useCurrentUser } from '@/features/auth/api';
import { formatDateTime } from '@/lib/time';
import { useCases, useCreateCase } from '../api';

/** Investigation cases: the bundles of events, reports, footage and notes operators keep
 * together. Operators and admins. */
export function CasesPage() {
  const { data: user } = useCurrentUser();
  const allowed = user?.role === 'admin' || user?.role === 'operator';
  const { data, isLoading, isError } = useCases({ enabled: allowed });
  const create = useCreateCase();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');

  if (!allowed) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-text-muted">
        <p>Cases are for operators and admins.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold text-text">Cases</h1>
          <p className="text-sm text-text-muted">
            Keep what belongs together: choose Save to case on a search result, an event or an
            incident report.
          </p>
        </div>
        <Button className="ml-auto" onClick={() => setOpen(true)}>
          New case
        </Button>
      </header>

      {isLoading && <p className="text-sm text-text-muted">Loading cases…</p>}
      {isError && (
        <p role="alert" className="text-sm text-sev-critical">
          Could not load cases. Check your connection and try again.
        </p>
      )}
      {data && data.length === 0 && (
        <div className="rounded-panel border border-dashed border-rule p-6 text-sm text-text-muted">
          <p className="font-medium text-text">No cases yet</p>
          <p>Create one, or save something from a search result to start one.</p>
        </div>
      )}
      {data && data.length > 0 && (
        <ul className="flex flex-col divide-y divide-rule rounded-panel border border-rule bg-surface">
          {data.map((c) => (
            <li key={c.id}>
              <Link
                to={`/cases/${c.id}`}
                className="flex items-center gap-3 p-3 hover:bg-surface-raised"
              >
                <span className="font-medium text-text">{c.title}</span>
                <span className="text-sm text-text-muted">
                  {c.item_count} item{c.item_count === 1 ? '' : 's'}
                  {c.status === 'closed' ? ' · closed' : ''}
                </span>
                <span className="ml-auto text-xs tabular-nums text-text-muted">
                  updated {formatDateTime(new Date(c.updated_at))}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={async (e) => {
              e.preventDefault();
              const created = await create.mutateAsync({ title: title.trim() });
              setOpen(false);
              setTitle('');
              navigate(`/cases/${created.id}`);
            }}
          >
            <DialogHeader>
              <DialogTitle>New case</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-1">
              <Label htmlFor="new-case-title">Name</Label>
              <Input
                id="new-case-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                maxLength={200}
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!title.trim() || create.isPending}>
                Create case
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
