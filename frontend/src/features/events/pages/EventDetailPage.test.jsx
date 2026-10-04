import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import acknowledged from '@/features/alerts/fixtures/alert_acknowledged.json';
import open from '@/features/alerts/fixtures/alert_open.json';
import groupDetail from '@/features/alerts/fixtures/correlation_group_detail.json';
import { ApiError, apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { EventDetailPage } from './EventDetailPage';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

// hls.js needs a real media pipeline; the page's job is to hand it the right playlist.
const hlsInstances = [];
vi.mock('hls.js', () => {
  class FakeHls {
    static isSupported = () => true;
    static Events = { ERROR: 'hlsError' };
    constructor(config) {
      this.config = config;
      this.handlers = {};
      this.destroyed = false;
      hlsInstances.push(this);
    }
    on(event, handler) {
      this.handlers[event] = handler;
    }
    loadSource(url) {
      this.url = url;
    }
    attachMedia(video) {
      this.video = video;
    }
    destroy() {
      this.destroyed = true;
    }
  }
  return { default: FakeHls };
});

function renderPage(role, { alert = open, extra = {}, id = alert?.id ?? 'x' } = {}) {
  const user = signedInAs(role);
  stubApi(apiClient, {
    'GET /auth/me': user,
    [`GET /alerts/${id}`]: alert,
    [`GET /correlations/${groupDetail.id}`]: groupDetail,
    ...extra,
  });
  return renderWithProviders(
    <Routes>
      <Route path="/events/:alertId" element={<EventDetailPage />} />
      <Route path="/events" element={<p>events list</p>} />
    </Routes>,
    { route: `/events/${id}` },
  );
}

describe('EventDetailPage', () => {
  beforeEach(() => {
    clearTokens();
    hlsInstances.length = 0;
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(toast.success).mockReset();
  });

  it('shows the title, severity, status and the facts', async () => {
    renderPage('operator');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Intrusion on cam02' }),
    ).toBeInTheDocument();
    expect(screen.getByText('High')).toBeInTheDocument();
    const details = within(screen.getByRole('heading', { name: 'Details' }).closest('section'));
    expect(details.getByText('cam02')).toBeInTheDocument();
    expect(details.getByText('intrusion.after_hours')).toBeInTheDocument();
    expect(details.getByText('01929e6c-0001-7000-8000-000000000001')).toBeInTheDocument();
    expect(details.getByText(/5 Oct, 15:45 to 15:45:42/)).toBeInTheDocument(); // IST, start to end
  });

  it('says "Whole camera" for a camera-wide rule', async () => {
    renderPage('operator', { alert: { ...open, zone_id: null } });
    expect(await screen.findByText('Whole camera')).toBeInTheDocument();
  });

  it("shows the model's description with how sure it was", async () => {
    renderPage('operator');
    expect(await screen.findByText(open.caption)).toBeInTheDocument();
    expect(screen.getByText('Verified by the vision model, 84% confidence.')).toBeInTheDocument();
    expect(screen.queryByText(/Low confidence/)).toBeNull();
  });

  it('warns plainly on low confidence (§B.8)', async () => {
    renderPage('operator', { alert: { ...open, confidence: 0.31 } });
    expect(
      await screen.findByText('Low confidence — review the clip before acting.'),
    ).toBeInTheDocument();
  });

  it('says so when the vision model was not asked and there is no description', async () => {
    renderPage('operator', { alert: acknowledged });
    expect(
      await screen.findByText('No description was generated for this event.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Not checked by the vision model.')).toBeInTheDocument();
  });

  it('points the player at the recording of this camera, 10 s either side of the event', async () => {
    renderPage('operator');
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(hlsInstances).toHaveLength(1));
    const url = new URL(hlsInstances[0].url, 'http://x');
    expect(url.pathname).toBe('/api/v1/recordings/cam02/playlist.m3u8');
    expect(url.searchParams.get('start')).toBe('2026-10-05T10:15:10.000Z');
    expect(url.searchParams.get('end')).toBe('2026-10-05T10:15:52.000Z');
    expect(typeof hlsInstances[0].config.xhrSetup).toBe('function'); // the manifest request is authenticated
    expect(screen.getByLabelText('Recording of cam02')).toBeInTheDocument();
  });

  it('releases the player when the page goes away', async () => {
    const { unmount } = renderPage('operator');
    await waitFor(() => expect(hlsInstances).toHaveLength(1));
    unmount();
    expect(hlsInstances[0].destroyed).toBe(true);
  });

  it('tells the operator when playback fails', async () => {
    renderPage('operator');
    await waitFor(() => expect(hlsInstances).toHaveLength(1));
    hlsInstances[0].handlers.hlsError(null, { fatal: true });
    expect(
      await screen.findByText('Playback failed. The recording may not cover this time.'),
    ).toBeInTheDocument();
  });

  it('shows the keyframes with a text alternative', async () => {
    renderPage('operator');
    const images = await screen.findAllByRole('img');
    expect(images).toHaveLength(2);
    expect(images[0]).toHaveAttribute('src', open.keyframe_urls[0]);
    expect(images[0]).toHaveAttribute('alt', 'Keyframe 1 of 2 from cam02');
  });

  it('explains an expired keyframe link and how to get a fresh one', async () => {
    renderPage('operator');
    const [first] = await screen.findAllByRole('img');
    first.dispatchEvent(new Event('error'));
    expect(await screen.findByText('Keyframe 1 could not be loaded.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Keyframe links expire after 15 minutes. Reload the page to get fresh ones.',
      ),
    ).toBeInTheDocument();
  });

  it('says so when an event has no keyframes', async () => {
    renderPage('operator', { alert: { ...acknowledged, keyframe_urls: [], keyframe_count: 0 } });
    expect(await screen.findByText('This event has no keyframes.')).toBeInTheDocument();
  });

  it('lists the correlated events in time order, marks this one, and says why they were linked', async () => {
    renderPage('operator');
    const section = within(
      (await screen.findByRole('heading', { name: 'Correlated events' })).closest('section'),
    );
    const rows = await section.findAllByRole('listitem');
    // 2 events + 1 link sentence
    const members = rows.filter((r) => r.dataset.eventId);
    expect(members.map((r) => r.dataset.eventId)).toEqual([
      '0192f3d1-0003-7000-8000-000000000003', // started first
      '0192f3d1-0001-7000-8000-000000000001',
    ]);
    expect(members[0]).toHaveTextContent('Abandoned object');
    expect(members[1]).toHaveTextContent('This event');
    expect(members[1]).toHaveAttribute('aria-current', 'true');
    expect(members[0]).not.toHaveAttribute('aria-current');
    expect(
      section.getByText(/Abandoned object on cam03, then Intrusion on cam02 28 s later/),
    ).toBeInTheDocument();
  });

  it('orders correlated events by when they started even if the api lists them otherwise', async () => {
    renderPage('operator', {
      extra: {
        [`GET /correlations/${groupDetail.id}`]: {
          ...groupDetail,
          members: [...groupDetail.members].reverse(), // latest first
        },
      },
    });
    const section = within(
      (await screen.findByRole('heading', { name: 'Correlated events' })).closest('section'),
    );
    const members = (await section.findAllByRole('listitem')).filter((r) => r.dataset.eventId);
    expect(members.map((r) => r.dataset.eventId)).toEqual([
      '0192f3d1-0003-7000-8000-000000000003',
      '0192f3d1-0001-7000-8000-000000000001',
    ]);
  });

  it('a group of one is "not linked": it is not even fetched', async () => {
    renderPage('operator', { alert: { ...open, group: { ...open.group, event_count: 1 } } });
    expect(await screen.findByText('Not linked with any other event.')).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/correlations/));
  });

  it('says it is not linked when the event stands alone, without asking for a group', async () => {
    renderPage('operator', { alert: { ...open, group: null } });
    expect(await screen.findByText('Not linked with any other event.')).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/correlations/));
  });

  it('copes with the correlated events failing to load', async () => {
    renderPage('operator', {
      extra: { [`GET /correlations/${groupDetail.id}`]: new Error('boom') },
    });
    expect(
      await screen.findByText(
        'Could not load the correlated events. Reload the page to try again.',
      ),
    ).toBeInTheDocument();
  });

  it('acknowledges from here: dialog, POST, toast, and the page shows it acknowledged', async () => {
    const acked = {
      ...open,
      status: 'acknowledged',
      acknowledged_at: '2026-10-05T10:16:20Z',
      ack_note: 'Guard sent',
    };
    renderPage('operator', { extra: { [`POST /alerts/${open.id}/ack`]: acked } });
    await userEvent.click(await screen.findByRole('button', { name: 'Acknowledge' }));
    await userEvent.type(screen.getByLabelText('Note (optional)'), 'Guard sent');
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Acknowledge' }),
    );

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(apiClient.post).toHaveBeenCalledWith(`/alerts/${open.id}/ack`, { note: 'Guard sent' });
    expect(toast.success).toHaveBeenCalledWith('Alert acknowledged');
    // the header status and the Details row both say so
    expect(await screen.findAllByText('Acknowledged')).toHaveLength(2);
    expect(screen.getByText(/, Guard sent/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull();
    // and the presigned urls from the first load were not lost by the update
    expect(screen.getAllByRole('img')).toHaveLength(2);
  });

  it('offers no actions on a resolved event', async () => {
    renderPage('operator', {
      alert: {
        ...open,
        status: 'resolved',
        resolved_at: '2026-10-05T10:20:00Z',
        resolve_note: 'False alarm',
      },
    });
    expect(await screen.findByText(/, False alarm/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Resolve' })).toBeNull();
  });

  it('says the event was not found for an unknown id, with a way back', async () => {
    renderPage('operator', {
      id: 'nope',
      alert: new ApiError('Alert not found.', { status: 404, code: 'NOT_FOUND' }),
    });
    expect(
      await screen.findByText('This event was not found. It may have been removed.'),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: 'All events' }));
    expect(await screen.findByText('events list')).toBeInTheDocument();
  });

  it('says what to do when the event cannot be loaded for another reason', async () => {
    renderPage('operator', { id: 'x', alert: new Error('network') });
    expect(
      await screen.findByText('Could not load this event. Check your connection and try again.'),
    ).toBeInTheDocument();
  });

  it('tells a viewer who sees events and never asks for the alert', async () => {
    renderPage('viewer');
    expect(
      await screen.findByText('Events are shown to operators and admins.'),
    ).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/alerts/));
  });
});
