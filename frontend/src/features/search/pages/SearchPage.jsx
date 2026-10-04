import { useRef, useState } from 'react';
import { Image as ImageIcon, Search, X } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCameras } from '@/features/cameras/api';
import { errorMessage } from '@/lib/errorMessage';
import { cn } from '@/lib/utils';
import { runImageSearch, runSearch } from '../api';
import { ResultCard } from '../components/ResultCard';
import { TIME_RANGES, planSummary, rangeFilter } from '../lib';

const EXAMPLES = [
  'a person in a red top near the service door',
  'someone carrying a backpack in the restricted yard',
  'people gathered in the plaza',
];

/** Reasoning-based search (FR-SRC): the operator describes what they are looking for in their own
 * words. A fast answer from image search appears at once; in "Reason" mode a language model
 * rereads the best candidates against the system's records and the ranking is replaced when it
 * finishes — with its working shown on each card.
 */
export function SearchPage() {
  const { data: cameras } = useCameras();
  const [text, setText] = useState('');
  const [mode, setMode] = useState('reason');
  const [camera, setCamera] = useState('');
  const [range, setRange] = useState('any');
  const [submitted, setSubmitted] = useState(null); // { id, kind, label, mode, filters }
  const [image, setImage] = useState(null);
  const fileRef = useRef(null);

  const filters = () => ({
    cameras: camera ? [camera] : [],
    ...rangeFilter(range),
  });

  function submitText(event) {
    event.preventDefault();
    if (text.trim().length < 2) return;
    setImage(null);
    setSubmitted({ id: Date.now(), kind: 'text', label: text.trim(), mode, filters: filters() });
  }

  function submitImage(file) {
    if (!file) return;
    setImage(file);
    setSubmitted({
      id: Date.now(),
      kind: 'image',
      label: file.name,
      mode: 'fast',
      filters: filters(),
      file,
    });
  }

  // Fast answer first; the reasoned answer replaces it when ready.
  const fast = useQuery({
    queryKey: ['search', 'fast', submitted?.id],
    enabled: Boolean(submitted),
    retry: false,
    staleTime: Infinity,
    queryFn: () =>
      submitted.kind === 'image'
        ? runImageSearch({ file: submitted.file, cameras: submitted.filters.cameras })
        : runSearch({ query: submitted.label, mode: 'fast', ...submitted.filters }),
  });
  const reasoned = useQuery({
    queryKey: ['search', 'reason', submitted?.id],
    enabled: Boolean(submitted) && submitted.kind === 'text' && submitted.mode === 'reason',
    retry: false,
    staleTime: Infinity,
    queryFn: () => runSearch({ query: submitted.label, mode: 'reason', ...submitted.filters }),
  });

  const reasonedOk = reasoned.isSuccess && reasoned.data.results.length > 0;
  const shown = reasonedOk ? reasoned.data : fast.data;
  const waitingOnReasoning =
    Boolean(submitted) && submitted.mode === 'reason' && reasoned.isFetching;
  const error = !shown && fast.isError ? fast.error : null;
  const total = shown?.timings_ms?.total;

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-text">Search footage</h1>
        <p className="text-sm text-text-muted">
          Describe what you are looking for. You do not need to know the camera or the time.
        </p>
      </header>

      <form onSubmit={submitText} className="flex flex-col gap-3" role="search">
        <div className="flex flex-wrap gap-2">
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={`For example: ${EXAMPLES[0]}`}
            aria-label="Describe what to find"
            className="min-w-64 flex-1"
          />
          <Button type="submit" disabled={text.trim().length < 2}>
            <Search size={16} aria-hidden="true" />
            Search
          </Button>
          <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}>
            <ImageIcon size={16} aria-hidden="true" />
            Search by image
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="sr-only"
            aria-label="Choose an image to search with"
            onChange={(e) => {
              submitImage(e.target.files?.[0]);
              e.target.value = '';
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <div
            role="group"
            aria-label="Search mode"
            className="flex rounded-panel border border-rule"
          >
            {[
              ['fast', 'Fast'],
              ['reason', 'Reason'],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
                className={cn(
                  'px-3 py-1 first:rounded-l-panel last:rounded-r-panel',
                  mode === value
                    ? 'bg-accent text-accent-ink'
                    : 'text-text hover:bg-surface-raised',
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-text-muted">
            Camera
            <select
              value={camera}
              onChange={(e) => setCamera(e.target.value)}
              className="h-9 rounded-panel border border-rule bg-surface px-2 text-sm text-text"
            >
              <option value="">All cameras</option>
              {(cameras?.items ?? []).map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-text-muted">
            When
            <select
              value={range}
              onChange={(e) => setRange(e.target.value)}
              className="h-9 rounded-panel border border-rule bg-surface px-2 text-sm text-text"
            >
              {TIME_RANGES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <span className="text-xs text-text-muted">
            {mode === 'reason'
              ? 'Reason mode rereads the best matches with a language model. It takes longer.'
              : 'Fast mode ranks by visual similarity only.'}
          </span>
        </div>
      </form>

      {image && (
        <p className="flex items-center gap-2 text-sm text-text-muted">
          Showing footage that looks like <strong className="text-text">{image.name}</strong>
          <button
            type="button"
            aria-label="Clear image"
            onClick={() => {
              setImage(null);
              setSubmitted(null);
            }}
            className="rounded-tile p-1 hover:bg-surface-raised"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </p>
      )}

      {!submitted && (
        <div className="flex flex-col gap-2 rounded-panel border border-dashed border-rule p-6 text-sm text-text-muted">
          <p className="font-medium text-text">Try one of these</p>
          <ul className="flex flex-col gap-1">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => setText(example)}
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {submitted && fast.isFetching && !shown && (
        <p role="status" className="text-sm text-text-muted">
          Searching the archive…
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-sev-critical">
          {errorMessage(error, {
            forbidden: 'You do not have access to search.',
            fallback: 'The search failed. Check your connection and try again.',
          })}
        </p>
      )}

      {shown && (
        <section aria-label="Results" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm text-text-muted">
            <span>
              {shown.results.length} result{shown.results.length === 1 ? '' : 's'}
              {reasonedOk ? ', ranked with reasoning' : ''}
            </span>
            {shown.plan && <span>Understood as: {planSummary(shown.plan) || 'free text'}</span>}
            {total != null && <span className="tabular-nums">{(total / 1000).toFixed(1)} s</span>}
          </div>
          {waitingOnReasoning && (
            <p role="status" className="text-sm text-text-muted">
              Showing the fast ranking. A language model is rereading the best matches…
            </p>
          )}
          {[...(fast.data?.notes ?? []), ...(reasoned.data?.notes ?? [])]
            .filter((n, i, all) => all.indexOf(n) === i)
            .map((note) => (
              <p key={note} className="text-sm text-text-muted">
                {note}
              </p>
            ))}
          {reasoned.isError && (
            <p className="text-sm text-text-muted">
              Reasoning is not available right now, so these are ranked by visual similarity.
            </p>
          )}
          {shown.results.length === 0 ? (
            <p className="rounded-panel border border-rule p-4 text-sm text-text-muted">
              Nothing in the archive matched. Try fewer details, or a wider time range.
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {shown.results.map((result, i) => (
                <ResultCard key={result.result_id} result={result} rank={i + 1} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
