import { describe, expect, it } from 'vitest';
import scheduled from './fixtures/zone_scheduled.json';
import plain from './fixtures/zone.json';
import {
  DEFAULT_SCHEDULE,
  canSave,
  describeDays,
  describeSchedule,
  detailProblems,
  draftFromZone,
  draftProblems,
  draftToPayload,
  newDraft,
} from './lib';

const SQUARE = [
  [0.2, 0.2],
  [0.8, 0.2],
  [0.8, 0.8],
  [0.2, 0.8],
];
const valid = (over = {}) => ({ ...newDraft(), name: 'Gate', points: SQUARE, ...over });

describe('newDraft', () => {
  it('starts empty, generic, with the schedule off but ready', () => {
    const draft = newDraft();
    expect(draft).toMatchObject({ name: '', zone_type: 'generic', points: [], scheduled: false });
    expect(draft.schedule).toEqual(DEFAULT_SCHEDULE);
  });

  it('does not share its schedule days with the next draft', () => {
    const first = newDraft();
    first.schedule.days.pop();
    expect(newDraft().schedule.days).toHaveLength(7);
    expect(DEFAULT_SCHEDULE.days).toHaveLength(7);
  });
});

describe('draftFromZone', () => {
  it('copies the zone, so editing the draft never edits the cached zone', () => {
    const draft = draftFromZone(scheduled);
    draft.points[0][0] = 0.99;
    draft.schedule.days.pop();
    expect(scheduled.polygon[0][0]).toBe(0.5);
    expect(scheduled.schedule.days).toHaveLength(5);
  });

  it('turns the schedule on only when the zone has one', () => {
    expect(draftFromZone(plain)).toMatchObject({ scheduled: false });
    expect(draftFromZone(plain).schedule).toEqual(DEFAULT_SCHEDULE);
    expect(draftFromZone(scheduled)).toMatchObject({ scheduled: true });
    expect(draftFromZone(scheduled).schedule).toEqual(scheduled.schedule);
  });
});

describe('detailProblems', () => {
  it('passes a named zone', () => {
    expect(detailProblems(valid())).toEqual({});
  });

  it('wants a name, and not one made only of spaces', () => {
    expect(detailProblems(valid({ name: '' })).name).toBe('Enter a name for the zone.');
    expect(detailProblems(valid({ name: '   ' })).name).toBe('Enter a name for the zone.');
  });

  it('allows 200 characters and not 201', () => {
    expect(detailProblems(valid({ name: 'a'.repeat(200) })).name).toBeUndefined();
    expect(detailProblems(valid({ name: 'a'.repeat(201) })).name).toBe(
      'Use 200 characters or fewer.',
    );
  });

  it('counts the name after trimming, as it will be sent', () => {
    expect(detailProblems(valid({ name: ` ${'a'.repeat(200)} ` })).name).toBeUndefined();
  });

  it('ignores the schedule while it is off, however wrong', () => {
    const bad = { ...DEFAULT_SCHEDULE, start_time: 'x', end_time: 'x', days: [] };
    expect(detailProblems(valid({ scheduled: false, schedule: bad }))).toEqual({});
  });

  it.each(['24:00', '08:60', '8:00', '', 'ab:cd', '08:00:00'])(
    'refuses the start time %j',
    (time) => {
      const problems = detailProblems(
        valid({ scheduled: true, schedule: { ...DEFAULT_SCHEDULE, start_time: time } }),
      );
      expect(problems.start_time).toBe('Enter a start time like 08:00.');
    },
  );

  it.each(['00:00', '23:59', '12:30'])('accepts the time %j', (time) => {
    const problems = detailProblems(
      valid({
        scheduled: true,
        schedule: { ...DEFAULT_SCHEDULE, start_time: '01:00', end_time: time },
      }),
    );
    expect(problems).toEqual({});
  });

  it('refuses a bad end time, and an end time equal to the start', () => {
    const at = (schedule) =>
      detailProblems(valid({ scheduled: true, schedule: { ...DEFAULT_SCHEDULE, ...schedule } }));
    expect(at({ end_time: '25:00' }).end_time).toBe('Enter an end time like 18:00.');
    expect(at({ start_time: '09:00', end_time: '09:00' }).end_time).toBe(
      "The end time can't equal the start time.",
    );
  });

  it('lets the window run past midnight', () => {
    const problems = detailProblems(
      valid({
        scheduled: true,
        schedule: { ...DEFAULT_SCHEDULE, start_time: '22:00', end_time: '06:00' },
      }),
    );
    expect(problems).toEqual({});
  });

  it('wants at least one day', () => {
    const problems = detailProblems(
      valid({ scheduled: true, schedule: { ...DEFAULT_SCHEDULE, days: [] } }),
    );
    expect(problems.days).toBe('Pick at least one day.');
  });

  it('refuses an unknown type', () => {
    expect(detailProblems(valid({ zone_type: 'secret' })).zone_type).toBe('Choose a zone type.');
  });
});

describe('draftProblems and canSave', () => {
  it('separates the details from the outline', () => {
    const { details, outline } = draftProblems(newDraft());
    expect(Object.keys(details)).toEqual(['name']);
    expect(outline).toHaveLength(1);
  });

  it('can save only when both are fine', () => {
    expect(canSave(valid())).toBe(true);
    expect(canSave(valid({ name: '' }))).toBe(false);
    expect(canSave(valid({ points: SQUARE.slice(0, 2) }))).toBe(false);
    expect(canSave(valid({ points: [SQUARE[0], SQUARE[2], SQUARE[1], SQUARE[3]] }))).toBe(false); // a bow-tie
  });
});

describe('draftToPayload', () => {
  it('sends the trimmed name, type, outline and no schedule when it is off', () => {
    expect(draftToPayload(valid({ name: '  Gate ', zone_type: 'entrance' }))).toEqual({
      name: 'Gate',
      zone_type: 'entrance',
      polygon: SQUARE,
      schedule: null,
    });
  });

  it('sends a null schedule even when the fields hold values, so editing it off clears it', () => {
    const draft = valid({
      scheduled: false,
      schedule: { ...DEFAULT_SCHEDULE, start_time: '01:00' },
    });
    expect(draftToPayload(draft).schedule).toBeNull();
  });

  it('sends the schedule, with the days in week order whatever order they were ticked', () => {
    const draft = valid({
      scheduled: true,
      schedule: { start_time: '22:00', end_time: '06:00', days: ['fri', 'mon', 'wed'] },
    });
    expect(draftToPayload(draft).schedule).toEqual({
      start_time: '22:00',
      end_time: '06:00',
      days: ['mon', 'wed', 'fri'],
    });
  });

  it('round-trips a zone through the form unchanged', () => {
    for (const zone of [plain, scheduled]) {
      const payload = draftToPayload(draftFromZone(zone));
      expect(payload).toEqual({
        name: zone.name,
        zone_type: zone.zone_type,
        polygon: zone.polygon,
        schedule: zone.schedule,
      });
    }
  });
});

describe('describeDays and describeSchedule', () => {
  it('names the common patterns', () => {
    expect(describeDays(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])).toBe('every day');
    expect(describeDays(['fri', 'thu', 'wed', 'tue', 'mon'])).toBe('weekdays');
    expect(describeDays(['sun', 'sat'])).toBe('weekends');
  });

  it('lists anything else in week order', () => {
    expect(describeDays(['fri', 'mon'])).toBe('Mon, Fri');
    expect(describeDays(['mon', 'tue', 'wed', 'thu', 'fri', 'sat'])).toBe(
      'Mon, Tue, Wed, Thu, Fri, Sat',
    );
  });

  it('summarises a schedule, or says "Always"', () => {
    expect(describeSchedule(null)).toBe('Always');
    expect(describeSchedule(scheduled.schedule)).toBe('22:00–06:00, weekdays');
    expect(describeSchedule({ start_time: '08:00', end_time: '18:00', days: ['sat'] })).toBe(
      '08:00–18:00, Sat',
    );
  });
});
