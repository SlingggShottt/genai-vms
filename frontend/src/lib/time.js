/** Times are stored as ISO UTC strings everywhere and formatted here in
 * Asia/Kolkata for display (docs/style_guide.md §A.2, §B.8).
 */
const IST_TIME_ZONE = 'Asia/Kolkata';

const clockFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: IST_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const dateFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: IST_TIME_ZONE,
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

/** `10:15:04` — wall-clock time, IST, per style_guide.md §B.8. */
export function formatClock(date = new Date()) {
  return clockFormatter.format(date);
}

/** `5 Oct, 10:15` — dated timestamp, IST, per style_guide.md §B.8. */
export function formatDateTime(date) {
  return dateFormatter.format(date);
}

const dayKeyFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: IST_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/** The clock time (`10:15:04`) for something that happened today in IST, the dated form
 * (`5 Oct, 10:15`) for anything older — §B.8.
 */
export function formatAbsolute(date, now = new Date()) {
  return dayKeyFormatter.format(date) === dayKeyFormatter.format(now)
    ? formatClock(date)
    : formatDateTime(date);
}

/** `2 min ago`  — always paired with an absolute time alongside it per
 * style_guide.md §B.8, never shown alone.
 */
export function formatRelative(date, now = new Date()) {
  const diffSeconds = Math.round((now.getTime() - date.getTime()) / 1000);
  if (diffSeconds < 5) return 'just now';
  if (diffSeconds < 60) return `${diffSeconds} sec ago`;
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes} min ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} hr ago`;
  return `${Math.round(diffHours / 24)} d ago`;
}
