import { DAYS, DAY_LABELS, ZONE_TYPES } from './schemas';
import { polygonProblems } from './polygon';

/** What the zone form edits: the api's fields, with the schedule held flat so its inputs stay
 * controlled whether or not the schedule is switched on. `points` is the outline being drawn.
 */
export const DEFAULT_SCHEDULE = { start_time: '08:00', end_time: '18:00', days: [...DAYS] };

export function newDraft() {
  return {
    name: '',
    zone_type: 'generic',
    points: [],
    scheduled: false,
    schedule: { ...DEFAULT_SCHEDULE, days: [...DEFAULT_SCHEDULE.days] },
  };
}

export function draftFromZone(zone) {
  return {
    name: zone.name,
    zone_type: zone.zone_type,
    points: zone.polygon.map(([x, y]) => [x, y]),
    scheduled: zone.schedule !== null,
    schedule: zone.schedule
      ? { ...zone.schedule, days: [...zone.schedule.days] }
      : { ...DEFAULT_SCHEDULE, days: [...DEFAULT_SCHEDULE.days] },
  };
}

const TIME_OF_DAY = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Problems with the zone's details (not its outline), by field, as messages that say what to fix. */
export function detailProblems(draft) {
  const problems = {};
  const name = draft.name.trim();
  if (!name) problems.name = 'Enter a name for the zone.';
  else if (name.length > 200) problems.name = 'Use 200 characters or fewer.';
  if (!ZONE_TYPES.includes(draft.zone_type)) problems.zone_type = 'Choose a zone type.';
  if (draft.scheduled) {
    const { start_time: start, end_time: end, days } = draft.schedule;
    if (!TIME_OF_DAY.test(start)) problems.start_time = 'Enter a start time like 08:00.';
    if (!TIME_OF_DAY.test(end)) problems.end_time = 'Enter an end time like 18:00.';
    else if (start === end) problems.end_time = "The end time can't equal the start time.";
    if (days.length === 0) problems.days = 'Pick at least one day.';
  }
  return problems;
}

/** Everything that blocks saving this draft. */
export function draftProblems(draft) {
  return { details: detailProblems(draft), outline: polygonProblems(draft.points) };
}

export function canSave(draft) {
  const { details, outline } = draftProblems(draft);
  return Object.keys(details).length === 0 && outline.length === 0;
}

/** The body for POST /cameras/{id}/zones and PATCH /zones/{id}. A PATCH with `schedule: null`
 * clears the schedule, which is what switching it off means.
 */
export function draftToPayload(draft) {
  return {
    name: draft.name.trim(),
    zone_type: draft.zone_type,
    polygon: draft.points,
    schedule: draft.scheduled
      ? {
          start_time: draft.schedule.start_time,
          end_time: draft.schedule.end_time,
          // The api keeps the order it is sent; week order reads best everywhere.
          days: DAYS.filter((day) => draft.schedule.days.includes(day)),
        }
      : null,
  };
}

/** "Mon to Fri" style summary of a day list; "every day" when all seven. */
export function describeDays(days) {
  const wanted = DAYS.filter((day) => days.includes(day));
  if (wanted.length === 7) return 'every day';
  if (wanted.join() === 'mon,tue,wed,thu,fri') return 'weekdays';
  if (wanted.join() === 'sat,sun') return 'weekends';
  return wanted.map((day) => DAY_LABELS[day]).join(', ');
}

/** "08:00–18:00, weekdays" — or "Always" for a zone with no schedule. */
export function describeSchedule(schedule) {
  if (!schedule) return 'Always';
  return `${schedule.start_time}–${schedule.end_time}, ${describeDays(schedule.days)}`;
}
