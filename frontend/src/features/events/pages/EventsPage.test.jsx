import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation, useNavigationType } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import acknowledged from '@/features/alerts/fixtures/alert_acknowledged.json';
import open from '@/features/alerts/fixtures/alert_open.json';
import { apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { EventsPage } from './EventsPage';

vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

const CAMERAS = {
  items: [
    {
      id: 'c2',
      code: 'cam02',
      name: 'North gate',
      rtsp_url: 'rtsp://x',
      site_id: 's',
      location_label: null,
      lat: null,
      lon: null,
      enabled: true,
      created_at: '2026-10-01T00:00:00Z',
    },
    {
      id: 'c4',
      code: 'cam04',
      name: 'Library',
      rtsp_url: 'rtsp://x',
      site_id: 's',
      location_label: null,
      lat: null,
      lon: null,
      enabled: true,
      created_at: '2026-10-01T00:00:00Z',
    },
  ],
  next_cursor: null,
};

function Probe() {
  const location = useLocation();
  const navigationType = useNavigationType();
  return (
    <>
      <output data-testid="url">{location.search}</output>
      <output data-testid="nav">{navigationType}</output>
    </>
  );
}

/** Calls made to `/alerts`, as URLSearchParams. */
const alertCalls = () =>
  apiClient.get.mock.calls
    .map(([p]) => p)
    .filter((p) => p.startsWith('/alerts'))
    .map((p) => new URLSearchParams(p.split('?')[1]));

function renderPage(role, { route = '/events', alerts } = {}) {
  const user = signedInAs(role);
  stubApi(apiClient, {
    'GET /auth/me': user,
    'GET /cameras': CAMERAS,
    'GET /alerts': alerts ?? { items: [open, acknowledged], next_cursor: null },
  });
  return renderWithProviders(
    <>
      <EventsPage />
      <Probe />
    </>,
    { route },
  );
}

describe('EventsPage', () => {
  beforeEach(() => {
    clearTokens();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
  });

  it('lists events newest first with time, severity, title link, camera, status and links', async () => {
    renderPage('operator');
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1); // minus the header
    expect(rows).toHaveLength(2);
    const first = within(rows[0]);
    expect(first.getByRole('link', { name: 'Intrusion on cam02' })).toHaveAttribute(
      'href',
      `/events/${open.id}`,
    );
    expect(first.getByText('High')).toBeInTheDocument();
    expect(first.getByText('cam02')).toBeInTheDocument();
    expect(first.getByText('Open')).toBeInTheDocument();
    expect(first.getByText('1')).toBeInTheDocument(); // linked with one other event
    expect(within(rows[1]).getByText('Acknowledged')).toBeInTheDocument();
    expect(within(rows[1]).getByText('None')).toBeInTheDocument();
    expect(screen.getByText('2 events shown')).toBeInTheDocument();
  });

  it('asks the api for no filters by default', async () => {
    renderPage('operator');
    await screen.findByRole('table');
    const params = alertCalls()[0];
    expect([...params.keys()].sort()).toEqual(['limit']);
  });

  it('applies a filter: sends it to the api and puts it in the url', async () => {
    renderPage('operator');
    await screen.findByRole('table');

    await userEvent.selectOptions(screen.getByLabelText('Status'), 'open');
    await userEvent.selectOptions(screen.getByLabelText('Severity'), 'critical');
    await userEvent.selectOptions(screen.getByLabelText('Camera'), 'cam02');

    await waitFor(() => {
      const last = alertCalls().at(-1);
      expect(last.getAll('status')).toEqual(['open']);
      expect(last.getAll('severity')).toEqual(['critical']);
      expect(last.get('camera_id')).toBe('cam02');
    });
    expect(screen.getByTestId('url')).toHaveTextContent(
      '?status=open&severity=critical&camera=cam02',
    );
  });

  it('changing a filter replaces the history entry: Back leaves the page, not the previous filter', async () => {
    renderPage('operator');
    await screen.findByRole('table');
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'open');
    await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent('status=open'));
    expect(screen.getByTestId('nav')).toHaveTextContent('REPLACE');
  });

  it('starts from the filters in the url (a shared link)', async () => {
    renderPage('operator', { route: '/events?status=resolved&camera=cam04&severity=urgent' });
    await screen.findByRole('table');
    expect(screen.getByLabelText('Status')).toHaveValue('resolved');
    expect(screen.getByLabelText('Camera')).toHaveValue('cam04');
    expect(screen.getByLabelText('Severity')).toHaveValue(''); // an unknown value is just "any"
    const first = alertCalls()[0];
    expect(first.getAll('status')).toEqual(['resolved']);
    expect(first.getAll('severity')).toEqual([]);
  });

  it('turns a time range into start/end for the api', async () => {
    renderPage('operator', { route: '/events?from=2026-10-05T10:00&to=2026-10-05T11:00' });
    await screen.findByRole('table');
    const params = alertCalls()[0];
    expect(params.get('start')).toBe(new Date('2026-10-05T10:00').toISOString());
    expect(params.get('end')).toBe(new Date('2026-10-05T11:00').toISOString());
  });

  it('explains a backwards range and does not send it', async () => {
    renderPage('operator', { route: '/events?from=2026-10-05T12:00&to=2026-10-05T10:00' });
    expect(await screen.findByText('End must be after start.')).toBeInTheDocument();
    await screen.findByRole('table');
    const params = alertCalls()[0];
    expect(params.has('start')).toBe(false);
    expect(params.has('end')).toBe(false);
  });

  it('clears every filter at once', async () => {
    renderPage('operator', { route: '/events?status=open&camera=cam02' });
    await screen.findByRole('table');
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent(/^$/));
    expect(screen.getByLabelText('Status')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeDisabled();
  });

  it('lists the cameras by name', async () => {
    renderPage('operator');
    await screen.findByRole('table');
    const camera = screen.getByLabelText('Camera');
    expect(within(camera).getByRole('option', { name: 'North gate' })).toHaveValue('cam02');
    expect(within(camera).getByRole('option', { name: 'All cameras' })).toHaveValue('');
  });

  it('shows more events with the cursor the api gave, and stops at the last page', async () => {
    const user = signedInAs('operator');
    stubApi(apiClient, {
      'GET /auth/me': user,
      'GET /cameras': CAMERAS,
      'GET /alerts': (path) =>
        new URLSearchParams(path.split('?')[1]).get('cursor') === 'c1'
          ? { items: [acknowledged], next_cursor: null }
          : { items: [open], next_cursor: 'c1' },
    });
    renderWithProviders(<EventsPage />, { route: '/events' });
    await screen.findByRole('table');
    expect(screen.getByText('1 event shown')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Show more' }));

    await waitFor(() => expect(screen.getByText('2 events shown')).toBeInTheDocument());
    expect(alertCalls().at(-1).get('cursor')).toBe('c1');
    expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull();
  });

  it('says what to do when there are no events at all', async () => {
    renderPage('operator', { alerts: { items: [], next_cursor: null } });
    expect(
      await screen.findByText(
        'No events yet. Events that raise an alert appear here once they are detected.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('says so when the filters match nothing, and how to see events again', async () => {
    renderPage('operator', {
      route: '/events?status=resolved',
      alerts: { items: [], next_cursor: null },
    });
    expect(
      await screen.findByText(
        'No events match these filters. Clear the filters to see every event that raised an alert.',
      ),
    ).toBeInTheDocument();
  });

  it('says what happened when the events cannot be loaded, and retries', async () => {
    renderPage('operator', { alerts: new Error('network') });
    expect(
      await screen.findByText('Could not load events. Check your connection and try again.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('tells a viewer who sees events, and never asks the api for them', async () => {
    renderPage('viewer');
    expect(
      await screen.findByText('Events are shown to operators and admins.'),
    ).toBeInTheDocument();
    expect(alertCalls()).toHaveLength(0);
  });
});
