import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { TimelinePage } from './TimelinePage';

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn() }),
  Toaster: () => null,
}));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

const NOW = Date.now();
const iso = (minutesAgo) => new Date(NOW - minutesAgo * 60e3).toISOString();

const TIMELINE = {
  start: iso(360),
  end: iso(0),
  cameras: ['cam01', 'cam02'],
  events: [
    {
      id: 'e1', camera_id: 'cam01', event_type: 'intrusion', severity: 'high',
      start: iso(60), end: iso(59), caption: 'a person at the fence', alert_id: 'a1',
    },
    {
      id: 'e2', camera_id: 'cam02', event_type: 'intrusion', severity: 'high',
      start: iso(59), end: iso(58), caption: null, alert_id: null,
    },
    {
      id: 'e3', camera_id: 'cam01', event_type: 'loitering', severity: 'low',
      start: iso(200), end: iso(199), caption: null, alert_id: null,
    },
  ],
  incidents: [],
  groups: [
    {
      id: 'g1', camera_ids: ['cam01', 'cam02'], severity: 'high', start: iso(60), end: iso(58),
      events: 2, event_ids: ['e1', 'e2'],
    },
  ],
}; // prettier-ignore

function render() {
  stubApi(apiClient, { 'GET /timeline': TIMELINE, 'GET /auth/me': signedInAs('operator') });
  return renderWithProviders(<TimelinePage />);
}

describe('TimelinePage', () => {
  beforeEach(() => {
    clearTokens();
    signedInAs('operator');
  });

  it('draws a lane per camera with its events', async () => {
    render();

    expect(await screen.findByRole('group', { name: 'Timeline of cam01' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Timeline of cam02' })).toBeInTheDocument();
    const lane = screen.getByRole('group', { name: 'Timeline of cam01' });
    expect(within(lane).getAllByRole('button')).toHaveLength(2);
  });

  it('outlines the events a group links and leaves the others plain', async () => {
    render();
    await screen.findByRole('group', { name: 'Timeline of cam01' });

    const linked = screen.getAllByRole('button', { name: /Intrusion event at/ });
    expect(linked).toHaveLength(2);
    linked.forEach((b) => expect(b.className).toContain('ring-accent'));
    const alone = screen.getByRole('button', { name: /Loitering event at/ });
    expect(alone.className).not.toContain('ring-accent');
    expect(linked[0]).toHaveAttribute(
      'title',
      expect.stringContaining('linked to events on other cameras'),
    );
  });

  it('shows each group as a bar on the Linked row and says which cameras it joins', async () => {
    render();
    const row = await screen.findByRole('group', { name: 'Events linked across cameras' });

    await userEvent.click(
      within(row).getByRole('button', { name: '2 events linked across cam01, cam02' }),
    );

    const aside = screen.getByRole('complementary', { name: 'Selected marker' });
    expect(aside).toHaveTextContent('2 events linked across cam01, cam02');
  });

  it('has no Linked row when nothing was linked', async () => {
    stubApi(apiClient, {
      'GET /timeline': { ...TIMELINE, groups: [] },
      'GET /auth/me': signedInAs('operator'),
    });
    renderWithProviders(<TimelinePage />);
    await screen.findByRole('group', { name: 'Timeline of cam01' });
    expect(screen.queryByRole('group', { name: 'Events linked across cameras' })).toBeNull();
  });

  it('turns a group into a selected period, and offers to search just that period', async () => {
    render();
    const row = await screen.findByRole('group', { name: 'Events linked across cameras' });
    await userEvent.click(within(row).getByRole('button', { name: /events linked across/ }));

    await userEvent.click(screen.getByRole('button', { name: 'Select this period' }));

    const link = await screen.findByRole('link', { name: 'Search in range' });
    const url = new URL(link.getAttribute('href'), 'http://x');
    expect(url.pathname).toBe('/search');
    expect(url.searchParams.get('camera')).toBe('cam01');
    expect(url.searchParams.get('start')).toBe(TIMELINE.groups[0].start);
    expect(url.searchParams.get('end')).toBe(TIMELINE.groups[0].end);
  });
});
