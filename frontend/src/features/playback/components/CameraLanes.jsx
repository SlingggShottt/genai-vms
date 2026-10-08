import { PHASE_LABEL } from '@/features/incidents/lib';
import { formatClock } from '@/lib/time';
import { cn } from '@/lib/utils';

// The same five fills as the incident page's phase band (§B.3: the name is on the segment too).
const FILL = {
  baseline: 'bg-surface-raised text-text',
  precursor: 'bg-sev-low-tint text-sev-low',
  escalation: 'bg-sev-medium-tint text-sev-medium',
  action: 'bg-sev-high-tint text-sev-high',
  aftermath: 'bg-accent-tint text-accent',
};

/** The phase band across camera lanes (§B.6): one lane per camera on a shared time axis, the
 * incident's phases drawn on each (the phases are located once, on the primary view, and apply to
 * every camera), and one playhead through all of them. Pressing a phase selects it; pressing
 * elsewhere in a lane moves the playhead.
 *
 * `spans`: `[{ phase, startMs, endMs }]` inside `[rangeStartMs, rangeEndMs]`.
 */
export function CameraLanes({
  lanes,
  spans,
  rangeStartMs,
  rangeEndMs,
  playheadMs,
  activePhase,
  onSelectPhase,
  onScrub,
}) {
  const total = Math.max(rangeEndMs - rangeStartMs, 1);
  const pct = (ms) =>
    `${(Math.min(Math.max((ms - rangeStartMs) / total, 0), 1) * 100).toFixed(2)}%`;

  function scrubFrom(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = (event.clientX - rect.left) / rect.width;
    onScrub?.(Math.round(rangeStartMs + Math.min(Math.max(ratio, 0), 1) * total));
  }

  return (
    <div className="relative flex flex-col gap-1" aria-label="Camera lanes">
      {lanes.map((lane) => (
        <div key={lane.key} className="flex items-center gap-2">
          <span className="w-28 shrink-0 truncate text-xs text-text-muted">{lane.label}</span>
          {/* The lane itself scrubs; the phases inside it select. */}
          {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- the slider above is the keyboard control */}
          <div
            onClick={scrubFrom}
            className="relative h-7 flex-1 cursor-pointer overflow-hidden rounded-tile border border-rule bg-surface"
          >
            {spans.map((s) => (
              <button
                key={s.phase}
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectPhase?.(s.phase);
                }}
                title={`${PHASE_LABEL[s.phase] ?? s.phase} ${formatClock(new Date(s.startMs))} to ${formatClock(new Date(s.endMs))}`}
                style={{ left: pct(s.startMs), width: `calc(${pct(s.endMs)} - ${pct(s.startMs)})` }}
                className={cn(
                  'absolute inset-y-0 min-w-1 overflow-hidden border-r border-rule px-1 text-left text-xs font-medium',
                  FILL[s.phase] ?? FILL.baseline,
                  activePhase === s.phase && 'ring-2 ring-inset ring-accent',
                )}
              >
                <span className="truncate">{PHASE_LABEL[s.phase] ?? s.phase}</span>
              </button>
            ))}
            <span
              aria-hidden="true"
              style={{ left: pct(playheadMs) }}
              className="pointer-events-none absolute inset-y-0 w-0.5 bg-accent"
            />
          </div>
        </div>
      ))}
    </div>
  );
}
