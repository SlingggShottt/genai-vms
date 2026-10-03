import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { createLiveSocket } from '@/lib/ws';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import acknowledged from '../fixtures/alert_acknowledged.json';
import open from '../fixtures/alert_open.json';
import wsCreated from '../fixtures/ws_alert_created.json';
import { FRESH_MS, LiveAlertsProvider } from '../LiveAlerts';
import { AlertTray } from './AlertTray';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock('@/lib/ws', () => ({ createLiveSocket: vi.fn() }));

/** The socket options the provider handed to `createLiveSocket`: the test plays the server. */
let socketOptions;
let socketCalls;
// What the api would answer to GET /alerts. A real server commits an alert before it pushes it, so
// a push is always preceded by `serverHas` — otherwise the tray's refetch would (rightly) erase it.
let serverItems;

function stubSocket() {
  socketCalls = { start: 0, stop: 0 };
  vi.mocked(createLiveSocket).mockImplementation((options) => {
    socketOptions = options;
    return {
      start: () => {
        socketCalls.start += 1;
      },
      stop: () => {
        socketCalls.stop += 1;
      },
    };
  });
}

const push = (message) => act(() => socketOptions.onMessage(message));
const status = (value) => act(() => socketOptions.onStatus(value));
const created = (alert) => ({ ...wsCreated, data: { ...alert, keyframe_urls: [] } });
const serverHas = (alert) => {
  serverItems = [alert, ...serverItems];
};
const pushCreated = async (alert) => {
  serverHas(alert);
  await push(created(alert));
};

function renderTray(role, { items = [open, acknowledged], extra = {}, openTray = true } = {}) {
  const user = signedInAs(role);
  serverItems = items;
  stubApi(apiClient, {
    'GET /auth/me': user,
    'GET /alerts': () => ({ items: serverItems, next_cursor: null }),
    ...extra,
  });
  return renderWithProviders(
    <LiveAlertsProvider>
      <AlertTray open={openTray} onToggle={() => {}} />
    </LiveAlertsProvider>,
  );
}

describe('AlertTray', () => {
  beforeEach(() => {
    clearTokens();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(toast.success).mockReset();
    stubSocket();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the alerts waiting for a person, newest first, with how many are still open', async () => {
    renderTray('operator');
    const list = await screen.findByRole('list');
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Intrusion on cam02')).toBeInTheDocument();
    expect(screen.getByText('1 open')).toBeInTheDocument(); // the acknowledged one is not "open"
    expect(apiClient.get).toHaveBeenCalledWith(
      expect.stringMatching(/^\/alerts\?.*status=open.*status=acknowledged/),
    );
  });

  it('is open to admins as well', async () => {
    renderTray('admin');
    expect(await screen.findByRole('list')).toBeInTheDocument();
  });

  it('tells a viewer who sees alerts, and never asks the api for them or opens a socket', async () => {
    renderTray('viewer');
    expect(
      await screen.findByText('Alerts are shown to operators and admins.'),
    ).toBeInTheDocument();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/auth/me'));
    expect(apiClient.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/alerts/));
    expect(socketCalls.start).toBe(0);
  });

  it('says what to do next when there is nothing to show (§B.7 empty states)', async () => {
    renderTray('operator', { items: [] });
    expect(
      await screen.findByText('No open alerts. New alerts appear here as events are detected.'),
    ).toBeInTheDocument();
  });

  it('says what happened and offers a retry when the alerts cannot be loaded', async () => {
    renderTray('operator', { extra: { 'GET /alerts': new Error('network') } });
    expect(
      await screen.findByText('Could not load alerts. Check your connection and try again.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('retries loading when asked, and shows the alerts once it works', async () => {
    let healthy = false;
    renderTray('operator', {
      extra: {
        'GET /alerts': () =>
          healthy ? { items: [open], next_cursor: null } : new Error('network down'),
      },
    });
    await screen.findByText('Could not load alerts. Check your connection and try again.');

    healthy = true;
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByRole('list')).toBeInTheDocument();
    expect(screen.queryByText(/Could not load alerts/)).toBeNull();
  });

  it('links to the Events page', async () => {
    renderTray('operator');
    expect(await screen.findByRole('link', { name: 'All events' })).toHaveAttribute(
      'href',
      '/events',
    );
  });

  it('collapses to a rail that still shows how many alerts are open', async () => {
    renderTray('operator', { openTray: false });
    expect(await screen.findByLabelText('Expand alert tray')).toBeInTheDocument();
    expect(await screen.findByText('1')).toBeInTheDocument();
    expect(screen.queryByRole('list')).toBeNull();
    // the live regions stay mounted: a collapsed tray still announces
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  describe('live updates', () => {
    it('opens one socket for an operator, and stops it when unmounted', async () => {
      const { unmount } = renderTray('operator');
      await screen.findByRole('list');
      expect(socketCalls.start).toBe(1);
      unmount();
      expect(socketCalls.stop).toBe(1);
    });

    it('shows a pushed alert in the tray', async () => {
      renderTray('operator', { items: [] });
      await screen.findByText(/No open alerts/);
      const callsBefore = apiClient.get.mock.calls.length;

      await pushCreated(open);

      const row = await screen.findByRole('listitem');
      expect(within(row).getByText('Intrusion on cam02')).toBeInTheDocument();
      expect(screen.getByText('1 open')).toBeInTheDocument();
      expect(callsBefore).toBeGreaterThan(0);
    });

    it('announces a new alert politely, and a critical one assertively', async () => {
      renderTray('operator', { items: [] });
      await screen.findByText(/No open alerts/);

      await pushCreated(open); // high
      expect(screen.getByRole('status')).toHaveTextContent('New high alert: Intrusion on cam02');
      expect(screen.getByRole('alert')).toBeEmptyDOMElement();

      await push(
        created({ ...open, id: '0192f3d1-a009-7000-8000-000000000009', severity: 'critical' }),
      );
      expect(screen.getByRole('alert')).toHaveTextContent('Critical alert: Intrusion on cam02');
      expect(screen.getByRole('status')).toHaveTextContent('New high alert');
    });

    it('announces two identical alerts one after the other (the node is replaced, not reused)', async () => {
      renderTray('operator', { items: [] });
      await screen.findByText(/No open alerts/);
      await pushCreated(open);
      const first = screen.getByRole('status').firstElementChild;
      await pushCreated({ ...open, id: '0192f3d1-a008-7000-8000-000000000008' });
      expect(screen.getByRole('status').firstElementChild).not.toBe(first);
    });

    it('pulses a new high alert once, then leaves it still', async () => {
      renderTray('operator', { items: [] });
      await screen.findByText(/No open alerts/);
      vi.useFakeTimers({ shouldAdvanceTime: true });

      await pushCreated(open);
      expect(screen.getByRole('listitem')).toHaveClass('alert-pulse-high');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(FRESH_MS + 50);
      });
      expect(screen.getByRole('listitem')).not.toHaveClass('alert-pulse-high');
    });

    it('does not pulse a medium alert, and does not pulse alerts that were already there', async () => {
      renderTray('operator');
      await screen.findByRole('list');
      expect(screen.getAllByRole('listitem')[0].className).not.toMatch(/alert-pulse/);

      // pushCreated, not push: the tray refetches after a push, and a server that has never heard of
      // the alert takes it away again as soon as that settles (it did, on a slower machine)
      await pushCreated({
        ...open,
        id: '0192f3d1-a007-7000-8000-000000000007',
        severity: 'medium',
      });
      const medium = screen.getAllByRole('listitem').find((li) => li.dataset.alertId.endsWith('7'));
      expect(medium.className).not.toMatch(/alert-pulse/);
    });

    it('moves an acknowledged alert on in place when another operator acts on it', async () => {
      renderTray('operator', { items: [open] });
      await screen.findByRole('list');
      await push({
        ...wsCreated,
        type: 'alert.updated',
        data: { ...open, keyframe_urls: [], status: 'acknowledged', ack_note: 'Seen by the guard' },
      });
      expect(await screen.findByText('Acknowledged: Seen by the guard')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull();
      expect(screen.queryByText('1 open')).toBeNull();
    });

    it('drops an alert from the tray when it is resolved elsewhere', async () => {
      renderTray('operator', { items: [open] });
      await screen.findByRole('list');
      await push({
        ...wsCreated,
        type: 'alert.updated',
        data: { ...open, keyframe_urls: [], status: 'resolved', resolved_at: open.created_at },
      });
      await waitFor(() => expect(screen.queryByRole('listitem')).toBeNull());
    });

    it('says when live updates are paused, and clears it when they resume', async () => {
      renderTray('operator');
      await screen.findByRole('list');
      await status('reconnecting');
      expect(screen.getByText('Live updates paused. Reconnecting…')).toBeInTheDocument();
      await status('live');
      expect(screen.queryByText(/Live updates paused/)).toBeNull();
      await status('offline');
      expect(
        screen.getByText('Live updates are off. Sign in again to resume.'),
      ).toBeInTheDocument();
    });

    it('refetches the alerts after a reconnect, because a push is only a hint', async () => {
      renderTray('operator');
      await screen.findByRole('list');
      const before = apiClient.get.mock.calls.filter(([p]) => p.startsWith('/alerts')).length;

      await act(async () => socketOptions.onOpen({ reconnect: false }));
      expect(apiClient.get.mock.calls.filter(([p]) => p.startsWith('/alerts'))).toHaveLength(
        before,
      );

      await act(async () => socketOptions.onOpen({ reconnect: true }));
      await waitFor(() =>
        expect(
          apiClient.get.mock.calls.filter(([p]) => p.startsWith('/alerts')).length,
        ).toBeGreaterThan(before),
      );
    });

    it('ignores messages that are not alerts', async () => {
      renderTray('operator');
      await screen.findByRole('list');
      await push({ type: 'camera.status', data: { camera: 'cam01' }, ts: open.created_at });
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
      expect(screen.getByRole('status')).toBeEmptyDOMElement();
    });
  });

  describe('acting on an alert', () => {
    it('acknowledges from the tray with a note: dialog, POST, toast, and the row updates', async () => {
      const acked = { ...open, status: 'acknowledged', ack_note: 'On my way' };
      renderTray('operator', {
        items: [open],
        extra: { [`POST /alerts/${open.id}/ack`]: acked },
      });
      await screen.findByRole('list');

      await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
      expect(screen.getByRole('dialog', { name: 'Acknowledge alert' })).toBeInTheDocument();
      await userEvent.type(screen.getByLabelText('Note (optional)'), 'On my way');
      await userEvent.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Acknowledge' }),
      );

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(apiClient.post).toHaveBeenCalledWith(`/alerts/${open.id}/ack`, { note: 'On my way' });
      expect(toast.success).toHaveBeenCalledWith('Alert acknowledged');
      expect(await screen.findByText('Acknowledged: On my way')).toBeInTheDocument();
    });

    it('a stale click (another operator got there first): says so and the tray shows what is true now', async () => {
      renderTray('operator', {
        items: [open],
        extra: {
          [`POST /alerts/${open.id}/ack`]: new ApiError('conflict', {
            status: 409,
            code: 'CONFLICT',
            details: { status: 'acknowledged' },
          }),
        },
      });
      await screen.findByRole('list');
      // meanwhile, someone else acknowledged it
      serverItems = [{ ...open, status: 'acknowledged', ack_note: 'Seen by the guard' }];

      await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
      await userEvent.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Acknowledge' }),
      );

      expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent(
        'This alert is already acknowledged',
      );
      expect(await screen.findByText('Acknowledged: Seen by the guard')).toBeInTheDocument(); // refetched
    });

    it('resolving removes the alert from the tray', async () => {
      renderTray('operator', {
        items: [open],
        extra: { [`POST /alerts/${open.id}/resolve`]: { ...open, status: 'resolved' } },
      });
      await screen.findByRole('list');

      await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));
      await userEvent.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Resolve' }),
      );

      await waitFor(() => expect(screen.queryByRole('listitem')).toBeNull());
      expect(toast.success).toHaveBeenCalledWith('Alert resolved');
    });
  });
});
