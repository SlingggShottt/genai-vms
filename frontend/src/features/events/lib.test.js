import { describe, expect, it } from 'vitest';
import { eventTypeLabel } from '@/lib/eventTypes';
import open from '../alerts/fixtures/alert_open.json';
import { CLIP_PADDING_S, LOW_CONFIDENCE, clipRange, describeLink, verificationNote } from './lib';

describe('clipRange', () => {
  it('pads the event window by 10 s on both sides', () => {
    expect(CLIP_PADDING_S).toBe(10);
    expect(clipRange(open)).toEqual({
      startIso: '2026-10-05T10:15:10.000Z', // event starts 10:15:20
      endIso: '2026-10-05T10:15:52.000Z', // event ends 10:15:42
    });
  });

  it('takes a custom padding', () => {
    expect(clipRange(open, 0)).toEqual({
      startIso: '2026-10-05T10:15:20.000Z',
      endIso: '2026-10-05T10:15:42.000Z',
    });
  });
});

describe('verificationNote', () => {
  it('reports the confidence as a percentage', () => {
    expect(verificationNote(open)).toEqual({
      text: 'Verified by the vision model, 84% confidence.',
      low: false,
    });
  });

  it('flags low confidence at and below the threshold side, not above it', () => {
    expect(LOW_CONFIDENCE).toBe(0.5);
    expect(verificationNote({ ...open, confidence: 0.49 }).low).toBe(true);
    expect(verificationNote({ ...open, confidence: 0.5 }).low).toBe(false);
    expect(verificationNote({ ...open, confidence: 0.2 }).text).toContain('20% confidence');
  });

  it('says plainly when the vision model never looked', () => {
    expect(verificationNote({ ...open, verification_status: 'skipped', confidence: null })).toEqual(
      { text: 'Not checked by the vision model.', low: false },
    );
  });

  it('copes with a verified event that carries no confidence', () => {
    expect(verificationNote({ ...open, confidence: null })).toEqual({
      text: 'Verified by the vision model.',
      low: false,
    });
  });
});

describe('describeLink', () => {
  const byEvent = new Map([
    ['a', { camera_id: 'cam03', event_type: 'abandoned_object' }],
    ['b', { camera_id: 'cam02', event_type: 'intrusion' }],
  ]);

  it('describes a transit link by the time between the two events', () => {
    expect(
      describeLink(
        { from_event: 'a', to_event: 'b', edge_type: 'transit', delta_s: 28.4, score: 0.6973 },
        byEvent,
      ),
    ).toBe(
      'Abandoned object on cam03, then Intrusion on cam02 28 s later (camera path, score 0.70)',
    );
  });

  it('rounds the seconds to the nearest, not down', () => {
    const link = {
      from_event: 'a',
      to_event: 'b',
      edge_type: 'transit',
      delta_s: 28.6,
      score: 0.7,
    };
    expect(describeLink(link, byEvent)).toContain('29 s later');
    expect(describeLink({ ...link, delta_s: 28.4 }, byEvent)).toContain('28 s later');
  });

  it('describes an overlap link as simultaneous or by its gap', () => {
    expect(
      describeLink(
        { from_event: 'a', to_event: 'b', edge_type: 'overlap', delta_s: 0, score: 0.9 },
        byEvent,
      ),
    ).toBe(
      'Abandoned object on cam03 and Intrusion on cam02, at the same time (overlapping views, score 0.90)',
    );
    expect(
      describeLink(
        { from_event: 'a', to_event: 'b', edge_type: 'overlap', delta_s: 3.2, score: 0.5 },
        byEvent,
      ),
    ).toContain('3 s apart');
  });

  it('copes with an event the group no longer lists', () => {
    expect(
      describeLink(
        { from_event: 'x', to_event: 'y', edge_type: 'transit', delta_s: 5, score: 0.5 },
        byEvent,
      ),
    ).toBe('An event, then an event 5 s later (camera path, score 0.50)');
  });
});

describe('eventTypeLabel', () => {
  it('uses sentence case for the known types', () => {
    expect(
      ['intrusion', 'loitering', 'crowding', 'abandoned_object', 'running'].map(eventTypeLabel),
    ).toEqual(['Intrusion', 'Loitering', 'Crowding', 'Abandoned object', 'Running']);
  });

  it('tidies an unknown type instead of hiding it', () => {
    expect(eventTypeLabel('fire-door_open')).toBe('Fire door open');
    expect(eventTypeLabel('')).toBe('Event');
    expect(eventTypeLabel(undefined)).toBe('Event');
  });
});
