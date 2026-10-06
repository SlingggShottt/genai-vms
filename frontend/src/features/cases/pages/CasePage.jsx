import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useCurrentUser } from '@/features/auth/api';
import { alertForEvent } from '@/features/assistant/api';
import { ApiError } from '@/lib/apiClient';
import { formatDateTime } from '@/lib/time';
import { useCase, useDeleteCase, useRemoveItem, useUpdateCase } from '../api';
import { KIND_LABEL, itemHref } from '../lib';

function ItemLink({ item }) {
  const navigate = useNavigate();
  const href = itemHref(item);
  const text = `${KIND_LABEL[item.kind]} · ${item.label}`;
  if (item.kind === 'event') {
    return (
      <button
        type="button"
        className="text-left text-accent hover:underline"
        onClick={async () => {
          try {
            const alertId = await alertForEvent(item.ref);
            if (alertId) navigate(`/events/${alertId}`);
            else toast('This event raised no alert, so it has no page of its own.');
          } catch {
            toast('Could not open the event. Try again.');
          }
        }}
      >
        {text}
      </button>
    );
  }
  return href ? (
    <Link to={href} className="text-accent hover:underline">
      {text}
    </Link>
  ) : (
    <span className="text-text">{text}</span>
  );
}

/** One case: its items in the order they were added, each a way back to the thing itself. */
export function CasePage() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const { data: user } = useCurrentUser();
  const allowed = user?.role === 'admin' || user?.role === 'operator';
  const { data: c, isLoading, isError, error } = useCase(allowed ? caseId : null);
  const update = useUpdateCase(caseId);
  const remove = useRemoveItem(caseId);
  const del = useDeleteCase();
  const [description, setDescription] = useState(null);

  if (!allowed) {
    return <p className="p-4 text-sm text-text-muted">Cases are for operators and admins.</p>;
  }
  if (isLoading) return <p className="p-4 text-sm text-text-muted">Loading case…</p>;
  if (isError || !c) {
    const missing = error instanceof ApiError && [400, 404].includes(error.status);
    return (
      <div className="flex flex-col items-start gap-2 p-4 text-sm text-text-muted">
        <p>{missing ? 'This case was not found.' : 'Could not load this case. Try again.'}</p>
        <Link to="/cases" className="text-accent hover:underline">
          All cases
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <Link to="/cases" className="text-sm text-accent hover:underline">
        All cases
      </Link>
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-text">{c.title}</h1>
        <span className="text-sm text-text-muted">{c.status === 'open' ? 'Open' : 'Closed'}</span>
        <div className="ml-auto flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => update.mutate({ status: c.status === 'open' ? 'closed' : 'open' })}
          >
            {c.status === 'open' ? 'Close case' : 'Reopen case'}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              await del.mutateAsync(c.id);
              navigate('/cases');
            }}
          >
            Delete case
          </Button>
        </div>
      </header>

      <div className="flex max-w-2xl flex-col gap-2">
        <Textarea
          aria-label="Case description"
          placeholder="What is this investigation about?"
          value={description ?? c.description ?? ''}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
        />
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          disabled={description === null || update.isPending}
          onClick={() => update.mutate({ description })}
        >
          Save description
        </Button>
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold text-text">Items ({c.items.length})</h2>
        {c.items.length === 0 ? (
          <p className="text-sm text-text-muted">
            Nothing saved yet. Choose Save to case on a search result, an event or an incident.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-rule rounded-panel border border-rule bg-surface">
            {c.items.map((item) => (
              <li key={item.id} className="flex items-start gap-3 p-3 text-sm">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <ItemLink item={item} />
                  {item.camera_id && item.ts_start && (
                    <span className="text-xs tabular-nums text-text-muted">
                      {item.camera_id} · {formatDateTime(new Date(item.ts_start))}
                    </span>
                  )}
                  {item.note && <p className="text-text">{item.note}</p>}
                </div>
                <button
                  type="button"
                  aria-label={`Remove ${item.label} from the case`}
                  className="rounded-tile p-1 text-text-muted hover:text-sev-critical"
                  onClick={() => remove.mutate(item.id)}
                >
                  <Trash2 size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
