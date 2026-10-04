import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { alertForEvent } from '../api';

const KIND_LABEL = { E: 'Event', I: 'Incident', S: 'Footage' };
const CHIP =
  'inline-flex items-center gap-1 rounded-pill border border-rule bg-surface-raised px-2 py-px align-baseline text-xs text-text hover:border-accent hover:text-accent';

export function playbackHref(citation, padSeconds = 6) {
  if (!citation.ts || !citation.camera) return null;
  const at = new Date(citation.ts).getTime();
  const params = new URLSearchParams({
    camera: citation.camera,
    start: new Date(at - padSeconds * 1000).toISOString(),
    end: new Date(at + (padSeconds + 4) * 1000).toISOString(),
  });
  return `/playback?${params.toString()}`;
}

/** A citation (§B.7 EvidenceChip): what the answer rests on, one press from the clip, the event
 * or the incident report. */
export function CitationChip({ citation }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const label = `${KIND_LABEL[citation.kind]} · ${citation.label}`;

  if (citation.kind === 'I') {
    return (
      <Link to={`/incidents/${citation.ref}`} className={CHIP} title={label}>
        {label}
      </Link>
    );
  }
  if (citation.kind === 'S') {
    const href = playbackHref(citation);
    return href ? (
      <Link to={href} className={CHIP} title="Open the recording at this moment">
        {label}
      </Link>
    ) : (
      <span className={cn(CHIP, 'cursor-default')}>{label}</span>
    );
  }
  return (
    <button
      type="button"
      disabled={busy}
      className={CHIP}
      title="Open the event"
      onClick={async () => {
        setBusy(true);
        try {
          const alertId = await alertForEvent(citation.ref);
          if (alertId) navigate(`/events/${alertId}`);
          else toast('This event raised no alert, so it has no page of its own.');
        } catch {
          toast('Could not open the event. Try again.');
        } finally {
          setBusy(false);
        }
      }}
    >
      {label}
    </button>
  );
}
