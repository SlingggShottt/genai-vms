import { cn } from '@/lib/utils';

/** A citation (§B.7): the id of a piece of evidence behind a claim. Pressing it highlights that
 * evidence in the page; the title says what it is.
 */
export function EvidenceChip({ id, info, active, onSelect }) {
  const label = id.replace(/^ev-/, '');
  return (
    <button
      type="button"
      onClick={() => onSelect?.(id)}
      title={info ? `${info.kind}: ${info.text}` : 'Evidence not found'}
      aria-label={`Evidence ${id}${info ? `, ${info.kind}` : ''}`}
      aria-pressed={active}
      className={cn(
        'rounded-pill border px-2 py-px font-condensed text-xs tabular-nums transition-colors',
        active
          ? 'border-accent bg-accent-tint text-accent'
          : 'border-rule bg-surface-raised text-text-muted hover:text-text',
      )}
    >
      {label}
    </button>
  );
}

export function EvidenceChips({ ids, index, active, onSelect }) {
  if (!ids?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) => (
        <EvidenceChip
          key={id}
          id={id}
          info={index.get(id)}
          active={active === id}
          onSelect={onSelect}
        />
      ))}
    </span>
  );
}
