import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatClock, formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { playbackLink } from '../lib';
import { useCurrentUser } from '@/features/auth/api';
import { AddToCaseDialog } from '@/features/cases/components/AddToCaseDialog';
import { MaskOverlay } from './MaskOverlay';

function Chip({ children }) {
  return (
    <span className="rounded-pill bg-surface-raised px-2 py-px text-xs text-text-muted">
      {children}
    </span>
  );
}

/** Reasoning trace (§B.7): why the model ranked this result, and what it could not tell. */
function PictureChecks({ answers }) {
  if (!answers?.length) return null;
  const mark = { yes: 'Yes', no: 'No', unsure: 'Cannot tell' };
  return (
    <div className="rounded-tile border border-rule p-2 text-xs">
      <p className="font-medium text-text">Checked in the picture</p>
      <ul className="mt-1 flex flex-col gap-0.5 text-text-muted">
        {answers.map((a) => (
          <li key={a.question}>
            {a.question} <strong className="font-medium text-text">{mark[a.answer]}</strong>
            {a.detail ? ` — ${a.detail}` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReasoningTrace({ result }) {
  const [open, setOpen] = useState(true);
  if (result.reasoning_score == null && !result.trace) return null;
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="rounded-tile border border-rule bg-surface-raised p-2 text-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1 text-left font-medium text-text"
      >
        <Icon size={14} aria-hidden="true" />
        Why this result
        {result.reasoning_score != null && (
          <span className="ml-auto text-xs font-normal tabular-nums text-text-muted">
            model score {Math.round(result.reasoning_score * 100)}
          </span>
        )}
      </button>
      {open && (
        <div className="mt-1 flex flex-col gap-1">
          {result.trace ? <p className="text-text">{result.trace}</p> : null}
          {result.missing?.length > 0 && (
            <p className="text-xs text-text-muted">
              Not shown by the records: {result.missing.join('; ')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** One ranked window of footage: the scene, who/what matched, and a way into the recording. */
export function ResultCard({ result, rank, searchId }) {
  const [imgFailed, setImgFailed] = useState(false);
  const { data: user } = useCurrentUser();
  const canSave = user?.role === 'admin' || user?.role === 'operator';
  const [saving, setSaving] = useState(null);
  const start = new Date(result.start_ts);
  const end = new Date(result.end_ts);
  const percent = Math.round(result.score * 100);
  const image = result.keyframe_url ?? result.crop_urls[0];

  return (
    <article
      aria-label={`Result ${rank}, ${result.camera_id}, ${formatClock(start)}`}
      className="flex flex-col overflow-hidden rounded-panel border border-rule bg-surface"
    >
      <div className="relative bg-video-bg">
        {image && !imgFailed ? (
          <img
            src={image}
            alt={`Frame from ${result.camera_id} at ${formatClock(start)}`}
            loading="lazy"
            onError={() => setImgFailed(true)}
            className="aspect-video w-full object-cover"
          />
        ) : (
          <p className="flex aspect-video items-center justify-center p-3 text-center text-xs text-text-muted">
            No frame available for this result.
          </p>
        )}
        {result.keyframe_url && !imgFailed && searchId && (
          <MaskOverlay searchId={searchId} resultId={result.result_id} />
        )}
        <span className="absolute left-2 top-2 rounded-pill bg-scrim px-2 py-px text-xs font-medium tabular-nums text-white">
          {percent}% match
        </span>
        {result.crop_urls.length > 0 && result.keyframe_url && (
          <div className="absolute bottom-2 right-2 flex gap-1">
            {result.crop_urls.slice(0, 3).map((u) => (
              <img
                key={u}
                src={u}
                alt="Matched object"
                loading="lazy"
                className="h-12 w-9 rounded-tile border border-white/60 object-cover"
              />
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-baseline gap-2 text-sm">
          <span className="font-condensed font-medium text-text">{result.camera_id}</span>
          <span className="tabular-nums text-text-muted">
            {formatDateTime(start)} to {formatClock(end)}
          </span>
        </div>

        {result.caption && <p className="text-sm text-text">{result.caption}</p>}

        <div className="flex flex-wrap gap-1">
          {result.categories.map((c) => (
            <Chip key={`c-${c}`}>{c}</Chip>
          ))}
          {result.colors.slice(0, 4).map((c) => (
            <Chip key={`k-${c}`}>{c}</Chip>
          ))}
          {result.zones.map((z) => (
            <Chip key={`z-${z}`}>{z}</Chip>
          ))}
        </div>

        <ReasoningTrace result={result} />
        <PictureChecks answers={result.jit_answers} />

        <div className={cn('mt-auto flex items-center gap-3 pt-1 text-sm')}>
          <Link to={playbackLink(result)} className="text-accent hover:underline">
            Open in playback
          </Link>
          {canSave && (
            <button
              type="button"
              className="text-accent hover:underline"
              onClick={() =>
                setSaving({
                  kind: 'footage',
                  label: `${result.camera_id} ${formatClock(start)}`,
                  ref: result.segment_ids[0] ?? null,
                  camera_id: result.camera_id,
                  ts_start: result.start_ts,
                  ts_end: result.end_ts,
                })
              }
            >
              Save to case
            </button>
          )}
          {result.incident_ids?.length > 0 && (
            <Link
              to={`/incidents/${result.incident_ids[0]}`}
              className="text-accent hover:underline"
            >
              Incident report
            </Link>
          )}
          {result.event_ids.length > 0 && (
            <span className="text-xs text-text-muted">
              {result.event_ids.length} verified event{result.event_ids.length > 1 ? 's' : ''}
            </span>
          )}
        </div>
      </div>
      <AddToCaseDialog item={saving} onClose={() => setSaving(null)} />
    </article>
  );
}
