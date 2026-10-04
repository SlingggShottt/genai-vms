/** `2 min 5 s` for a number of seconds; null when there is no figure. */
export function formatSeconds(s) {
  if (s == null) return 'no data';
  if (s < 60) return `${s} s`;
  const minutes = Math.floor(s / 60);
  const rest = s % 60;
  if (minutes < 60) return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** 24 hour buckets, "00"…"23", zero where the report has none. */
export function hourSeries(byHour) {
  return Array.from({ length: 24 }, (_, h) => {
    const key = String(h).padStart(2, '0');
    return { hour: key, value: byHour?.[key] ?? 0 };
  });
}

export function periodLabel(report) {
  const fmt = (d) =>
    new Date(`${d}T00:00:00`).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  return report.date_from === report.date_to
    ? fmt(report.date_from)
    : `${fmt(report.date_from)} to ${fmt(report.date_to)}`;
}

export const STATUS_LABEL = {
  queued: 'Waiting',
  generating: 'Writing',
  ready: 'Ready',
  failed: 'Failed',
};

/** Today in the site's time zone as YYYY-MM-DD (the date inputs and the api speak site days). */
export function siteToday(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}

export function shiftDay(isoDay, delta) {
  const d = new Date(`${isoDay}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}
