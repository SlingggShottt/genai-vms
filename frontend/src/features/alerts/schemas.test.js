import { describe, expect, it } from 'vitest';
import acknowledged from './fixtures/alert_acknowledged.json';
import open from './fixtures/alert_open.json';
import alertsPage from './fixtures/alerts_page.json';
import groupDetail from './fixtures/correlation_group_detail.json';
import wsCreated from './fixtures/ws_alert_created.json';
import wsUpdated from './fixtures/ws_alert_updated.json';
import {
  alertSchema,
  alertsPageSchema,
  canSeeAlerts,
  correlationGroupDetailSchema,
  wsEnvelopeSchema,
} from './schemas';

describe('alert schemas against what the api sends', () => {
  it('parses an open alert with its group and presigned keyframes', () => {
    const alert = alertSchema.parse(open);
    expect(alert.severity).toBe('high');
    expect(alert.group?.event_count).toBe(2);
    expect(alert.keyframe_urls).toHaveLength(2);
    expect(alert.keyframe_count).toBe(2);
  });

  it('parses an acknowledged alert with no group, caption or keyframes', () => {
    const alert = alertSchema.parse(acknowledged);
    expect(alert.status).toBe('acknowledged');
    expect(alert.ack_note).toBe('Guard sent to the north gate.');
    expect(alert.group).toBeNull();
    expect(alert.caption).toBeNull();
    expect(alert.confidence).toBeNull();
    expect(alert.camera_id).toBeNull();
  });

  it('parses a page and keeps its cursor', () => {
    const page = alertsPageSchema.parse(alertsPage);
    expect(page.items).toHaveLength(2);
    expect(page.next_cursor).toMatch(/^0192f3d1/);
  });

  it('parses a correlation group with members and links', () => {
    const group = correlationGroupDetailSchema.parse(groupDetail);
    expect(group.members.map((m) => m.camera_id).sort()).toEqual(['cam02', 'cam03']);
    expect(group.links[0]).toMatchObject({ edge_type: 'transit', delta_s: 28 });
  });

  it('parses the WebSocket envelope and its alert payload (no urls on a push)', () => {
    for (const message of [wsCreated, wsUpdated]) {
      const envelope = wsEnvelopeSchema.parse(message);
      const alert = alertSchema.parse(envelope.data);
      expect(alert.keyframe_urls).toEqual([]);
      expect(alert.keyframe_count).toBe(2);
    }
    expect(wsEnvelopeSchema.parse(wsUpdated).type).toBe('alert.updated');
  });

  it('rejects what it should: an unknown severity, a missing field, a naive timestamp', () => {
    expect(() => alertSchema.parse({ ...open, severity: 'urgent' })).toThrow();
    const { title: _title, ...withoutTitle } = open;
    expect(() => alertSchema.parse(withoutTitle)).toThrow();
    expect(() => alertSchema.parse({ ...open, start_ts: '2026-10-05T10:15:20' })).toThrow();
    expect(() => wsEnvelopeSchema.parse({ type: '', data: {}, ts: open.created_at })).toThrow();
  });

  it('accepts an explicit UTC offset as well as Z', () => {
    expect(alertSchema.parse({ ...open, start_ts: '2026-10-05T10:15:20+00:00' }).start_ts).toBe(
      '2026-10-05T10:15:20+00:00',
    );
  });
});

describe('canSeeAlerts', () => {
  it.each([
    ['admin', true],
    ['operator', true],
    ['viewer', false],
    [undefined, false],
  ])('role %s -> %s', (role, expected) => {
    expect(canSeeAlerts(role ? { role } : undefined)).toBe(expected);
  });
});
