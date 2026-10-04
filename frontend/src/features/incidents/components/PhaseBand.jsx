import { formatClock } from '@/lib/time';
import { cn } from '@/lib/utils';
import { PHASE_LABEL, phaseShares } from '../lib';

// Five phases, five fills, in the severity ramp's order (quiet → incident → after): all are
// existing tokens, and each segment also carries its name, so colour is never the only cue (§B.3).
const FILL = {
  baseline: 'bg-surface-raised text-text',
  precursor: 'bg-sev-low-tint text-sev-low',
  escalation: 'bg-sev-medium-tint text-sev-medium',
  action: 'bg-sev-high-tint text-sev-high',
  aftermath: 'bg-accent-tint text-accent',
};

/** The phase band (§B.6): the incident's window as one bar, a segment per phase. */
export function PhaseBand({ timeline, activePhase, onSelect }) {
  const shares = phaseShares(timeline);
  if (!shares.length) return null;
  return (
    <ul
      aria-label="Phase timeline"
      className="flex h-12 w-full overflow-hidden rounded-panel border border-rule"
    >
      {shares.map((p) => {
        const from = formatClock(new Date(p.start));
        const to = formatClock(new Date(p.end));
        return (
          <li
            key={p.phase}
            style={{ flexGrow: p.share, flexBasis: 0 }}
            className="min-w-0 border-r border-rule last:border-r-0"
          >
            <button
              type="button"
              onClick={() => onSelect?.(p.phase)}
              title={`${PHASE_LABEL[p.phase]} ${from} to ${to}`}
              className={cn(
                'flex h-full w-full min-w-0 flex-col items-start justify-center px-2 text-left',
                FILL[p.phase] ?? FILL.baseline,
                activePhase === p.phase && 'ring-2 ring-inset ring-accent',
              )}
            >
              <span className="truncate text-xs font-semibold">
                {PHASE_LABEL[p.phase] ?? p.phase}
              </span>
              <span className="truncate text-xs tabular-nums opacity-80">{from}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
