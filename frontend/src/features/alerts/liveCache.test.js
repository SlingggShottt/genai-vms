import { QueryClient } from '@tanstack/react-query';
import { beforeEach, describe, expect, it } from 'vitest';
import acknowledged from './fixtures/alert_acknowledged.json';
import open from './fixtures/alert_open.json';
import wsCreated from './fixtures/ws_alert_created.json';
import wsUpdated from './fixtures/ws_alert_updated.json';
import {
  announcementFor,
  applyAlert,
  applyAlertToList,
  applyAlertToTray,
  handleLiveMessage,
  mergeAlert,
  newestFirst,
  shouldPulse,
} from './liveCache';
import { TRAY_KEY, alertKey, listKey } from './queries';

const withId = (alert, id, extra = {}) => ({ ...alert, id, ...extra });
const pushed = { ...open, keyframe_urls: [] }; // what a WebSocket push carries

describe('mergeAlert', () => {
  it('keeps the presigned urls we hold when a push (no urls) updates the alert', () => {
    const merged = mergeAlert(open, { ...pushed, status: 'acknowledged' });
    expect(merged.status).toBe('acknowledged');
    expect(merged.keyframe_urls).toEqual(open.keyframe_urls);
  });

  it('takes fresh urls when the incoming alert has them', () => {
    const fresh = { ...open, keyframe_urls: ['http://new/1.jpg'] };
    expect(mergeAlert(open, fresh).keyframe_urls).toEqual(['http://new/1.jpg']);
  });

  it('is just the incoming alert when nothing is cached', () => {
    expect(mergeAlert(undefined, pushed)).toBe(pushed);
  });
});

describe('newestFirst', () => {
  it('orders by id, which is creation order (UUIDv7), without mutating its input', () => {
    const a = withId(open, '0192-a');
    const b = withId(open, '0192-c');
    const c = withId(open, '0192-b');
    const input = [a, b, c];
    expect(newestFirst(input).map((x) => x.id)).toEqual(['0192-c', '0192-b', '0192-a']);
    expect(input.map((x) => x.id)).toEqual(['0192-a', '0192-c', '0192-b']);
  });
});

describe('applyAlertToTray', () => {
  const page = { items: [withId(open, 'b'), withId(open, 'a')], next_cursor: null };

  it('does nothing before the tray has loaded', () => {
    expect(applyAlertToTray(undefined, open)).toBeUndefined();
  });

  it('adds a new alert at the top', () => {
    const result = applyAlertToTray(page, withId(open, 'c'));
    expect(result.items.map((i) => i.id)).toEqual(['c', 'b', 'a']);
  });

  it('changes an alert in place without moving it', () => {
    const result = applyAlertToTray(page, withId(open, 'a', { status: 'acknowledged' }));
    expect(result.items.map((i) => [i.id, i.status])).toEqual([
      ['b', 'open'],
      ['a', 'acknowledged'],
    ]);
  });

  it('removes an alert once it is resolved', () => {
    const result = applyAlertToTray(page, withId(open, 'b', { status: 'resolved' }));
    expect(result.items.map((i) => i.id)).toEqual(['a']);
  });

  it('returns the very same page when a resolved alert was not in it', () => {
    expect(applyAlertToTray(page, withId(open, 'zzz', { status: 'resolved' }))).toBe(page);
  });

  it('adding the same alert twice leaves one copy (a replayed push)', () => {
    const once = applyAlertToTray(page, withId(open, 'c'));
    const twice = applyAlertToTray(once, withId(open, 'c'));
    expect(twice.items.filter((i) => i.id === 'c')).toHaveLength(1);
  });
});

describe('applyAlertToList', () => {
  const data = {
    pages: [
      { items: [withId(open, 'a')], next_cursor: 'x' },
      { items: [withId(open, 'b')], next_cursor: null },
    ],
    pageParams: [undefined, 'x'],
  };

  it('replaces the alert wherever it appears, on any page', () => {
    const result = applyAlertToList(
      data,
      withId(open, 'b', { status: 'resolved', keyframe_urls: [] }),
    );
    expect(result.pages[1].items[0].status).toBe('resolved');
    expect(result.pages[1].items[0].keyframe_urls).toEqual(open.keyframe_urls); // urls kept
    expect(result.pages[0].items[0].status).toBe('open');
    expect(result.pageParams).toEqual(data.pageParams);
  });

  it('does not add an alert the list does not hold (a filter may exclude it)', () => {
    const result = applyAlertToList(data, withId(open, 'new'));
    expect(result.pages.flatMap((p) => p.items.map((i) => i.id))).toEqual(['a', 'b']);
  });

  it('ignores a list that has not loaded', () => {
    expect(applyAlertToList(undefined, open)).toBeUndefined();
  });
});

describe('applyAlert and handleLiveMessage on a real QueryClient', () => {
  let queryClient;
  beforeEach(() => {
    queryClient = new QueryClient();
  });

  const invalidated = (key) =>
    queryClient.getQueryCache().find({ queryKey: key })?.state.isInvalidated;

  it('puts a changed alert into the tray, the detail and the lists, and refetches the lists', () => {
    queryClient.setQueryData(TRAY_KEY, { items: [open], next_cursor: null });
    queryClient.setQueryData(alertKey(open.id), open);
    queryClient.setQueryData(listKey({ status: ['open'] }), {
      pages: [{ items: [open], next_cursor: null }],
      pageParams: [undefined],
    });

    applyAlert(queryClient, { ...pushed, status: 'acknowledged', ack_note: 'On my way' });

    expect(queryClient.getQueryData(TRAY_KEY).items[0]).toMatchObject({
      status: 'acknowledged',
      keyframe_urls: open.keyframe_urls,
    });
    expect(queryClient.getQueryData(alertKey(open.id)).ack_note).toBe('On my way');
    expect(queryClient.getQueryData(listKey({ status: ['open'] })).pages[0].items[0].status).toBe(
      'acknowledged',
    );
    expect(invalidated(listKey({ status: ['open'] }))).toBe(true);
  });

  it('does not create a detail entry from a push (it would have no urls)', () => {
    applyAlert(queryClient, pushed);
    expect(queryClient.getQueryData(alertKey(pushed.id))).toBeUndefined();
  });

  it('refetches the tray when an alert it does not hold turns up (the payload alone is not the page)', () => {
    queryClient.setQueryData(TRAY_KEY, { items: [], next_cursor: null });
    applyAlert(queryClient, pushed);
    expect(queryClient.getQueryData(TRAY_KEY).items.map((i) => i.id)).toEqual([pushed.id]);
    expect(invalidated(TRAY_KEY)).toBe(true);
  });

  it('turns an alert.created message into a tray entry', () => {
    queryClient.setQueryData(TRAY_KEY, { items: [], next_cursor: null });
    const result = handleLiveMessage(queryClient, wsCreated);
    expect(result.kind).toBe('created');
    expect(result.alert.id).toBe(open.id);
    expect(queryClient.getQueryData(TRAY_KEY).items).toHaveLength(1);
  });

  it('turns an alert.updated message into an update', () => {
    queryClient.setQueryData(TRAY_KEY, { items: [open], next_cursor: null });
    const result = handleLiveMessage(queryClient, wsUpdated);
    expect(result.kind).toBe('updated');
    expect(queryClient.getQueryData(TRAY_KEY).items[0].status).toBe('acknowledged');
  });

  it('removes a resolved alert from the tray', () => {
    queryClient.setQueryData(TRAY_KEY, { items: [open, acknowledged], next_cursor: null });
    handleLiveMessage(queryClient, {
      ...wsUpdated,
      data: { ...wsUpdated.data, status: 'resolved', resolved_at: '2026-10-05T10:20:00Z' },
    });
    expect(queryClient.getQueryData(TRAY_KEY).items.map((i) => i.id)).toEqual([acknowledged.id]);
  });

  it.each(['camera.status', 'job.progress', 'incident.ready', 'something.new'])(
    'ignores %s (not an alert)',
    (type) => {
      queryClient.setQueryData(TRAY_KEY, { items: [open], next_cursor: null });
      const result = handleLiveMessage(queryClient, { type, data: { x: 1 }, ts: open.created_at });
      expect(result).toEqual({ kind: 'ignored' });
      expect(queryClient.getQueryData(TRAY_KEY).items).toHaveLength(1);
      expect(invalidated(TRAY_KEY)).toBe(false); // a camera message must not make us refetch alerts
    },
  );

  it.each([null, 'text', 42, {}, { type: 'alert.created' }, { type: '', data: {}, ts: 'x' }])(
    'ignores a malformed envelope %j',
    (raw) => {
      expect(handleLiveMessage(queryClient, raw)).toEqual({ kind: 'ignored' });
    },
  );

  it('does not trust a malformed alert payload: it refetches the alerts instead', () => {
    queryClient.setQueryData(TRAY_KEY, { items: [open], next_cursor: null });
    const result = handleLiveMessage(queryClient, {
      ...wsCreated,
      data: { ...wsCreated.data, severity: 'urgent' },
    });
    expect(result).toEqual({ kind: 'ignored' });
    expect(invalidated(TRAY_KEY)).toBe(true);
    expect(queryClient.getQueryData(TRAY_KEY).items).toHaveLength(1);
  });
});

describe('announcementFor and shouldPulse', () => {
  it('announces critical alerts assertively and everything else politely', () => {
    expect(announcementFor({ severity: 'critical', title: 'Intrusion on cam02' })).toEqual({
      level: 'assertive',
      text: 'Critical alert: Intrusion on cam02',
    });
    for (const severity of ['low', 'medium', 'high']) {
      expect(announcementFor({ severity, title: 'Running on cam04' })).toEqual({
        level: 'polite',
        text: `New ${severity} alert: Running on cam04`,
      });
    }
  });

  it('pulses only high and critical alerts', () => {
    expect(
      ['low', 'medium', 'high', 'critical'].map((severity) => shouldPulse({ severity })),
    ).toEqual([false, false, true, true]);
  });
});
