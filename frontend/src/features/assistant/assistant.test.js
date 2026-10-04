import { describe, expect, it } from 'vitest';
import { segments } from './components/ChatMessage';
import { playbackHref } from './components/CitationChip';
import { parseSse } from './stream';

const cite = (kind, tag, extra = {}) => ({ kind, tag, ref: `${kind}-ref`, label: 'x', ...extra });

describe('parseSse', () => {
  it('splits complete events and keeps a partial one for the next read', () => {
    const first = parseSse('event: token\ndata: {"type":"token","text":"Hi"}\n\nevent: do');
    expect(first.events).toEqual([{ event: 'token', data: { type: 'token', text: 'Hi' } }]);
    const next = parseSse(`${first.rest}ne\ndata: {"type":"done"}\n\n`);
    expect(next.events[0].event).toBe('done');
  });

  it('skips a malformed block instead of failing the stream', () => {
    const { events } = parseSse('event: token\ndata: {oops\n\nevent: done\ndata: {"ok":1}\n\n');
    expect(events).toEqual([{ event: 'done', data: { ok: 1 } }]);
  });
});

describe('segments', () => {
  it('turns tags the server handed out into citations and drops invented ones', () => {
    const out = segments('One event [E:aaaa1111] and a fake [I:deadbeef].', [
      cite('E', 'aaaa1111'),
    ]);
    expect(out.filter((s) => s.citation)).toHaveLength(1);
    expect(out.map((s) => s.text ?? '').join('')).not.toContain('deadbeef');
  });

  it('never draws a consulted record as if the model had cited it', () => {
    const out = segments('Text [E:aaaa1111]', [cite('E', 'aaaa1111', { consulted: true })]);
    expect(out.some((s) => s.citation)).toBe(false);
  });
});

describe('playbackHref', () => {
  it('opens a window around the moment, and needs a camera and a time', () => {
    const href = playbackHref({ camera: 'cam01', ts: '2026-10-04T06:30:00Z' });
    const params = new URLSearchParams(href.split('?')[1]);
    expect(params.get('camera')).toBe('cam01');
    expect(new Date(params.get('end')) - new Date(params.get('start'))).toBe(16000);
    expect(playbackHref({ ts: '2026-10-04T06:30:00Z' })).toBeNull();
  });
});
