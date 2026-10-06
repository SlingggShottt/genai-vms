import { cn } from '@/lib/utils';

/** A small bar chart made of divs: every bar carries its number as text (a screen reader and a
 * printout need it, and colour alone says nothing — §B.3). Horizontal for a few named rows,
 * vertical (`columns`) for the 24-hour profile. */
export function HorizontalBars({ rows, label }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (rows.length === 0) return <p className="text-sm text-text-muted">Nothing recorded.</p>;
  return (
    <ul aria-label={label} className="flex flex-col gap-1.5">
      {rows.map((r) => (
        <li key={r.name} className="grid grid-cols-[8rem_1fr_2.5rem] items-center gap-2 text-sm">
          <span className="truncate text-text">{r.name}</span>
          <span className="h-3 rounded-pill bg-surface-raised">
            <span
              className="block h-3 rounded-pill bg-accent"
              style={{ width: `${(r.value / max) * 100}%` }}
            />
          </span>
          <span className="text-right tabular-nums text-text-muted">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

export function HourColumns({ series, label }) {
  const max = Math.max(1, ...series.map((s) => s.value));
  return (
    <figure aria-label={label} className="flex flex-col gap-1">
      <div className="flex h-32 items-end gap-0.5">
        {series.map((s) => (
          <div
            key={s.hour}
            title={`${s.hour}:00 — ${s.value} event${s.value === 1 ? '' : 's'}`}
            className="flex h-full flex-1 flex-col justify-end"
          >
            <span className="mb-0.5 text-center text-[10px] leading-none tabular-nums text-text-muted">
              {s.value > 0 ? s.value : ''}
            </span>
            <span
              className={cn(
                'block w-full rounded-t-tile',
                s.value > 0 ? 'bg-accent' : 'bg-surface-raised',
              )}
              style={{ height: `${Math.max((s.value / max) * 100, s.value > 0 ? 4 : 1)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-0.5 text-[10px] tabular-nums text-text-muted">
        {series.map((s) => (
          <span key={s.hour} className="flex-1 text-center">
            {Number(s.hour) % 3 === 0 ? s.hour : ''}
          </span>
        ))}
      </div>
    </figure>
  );
}
