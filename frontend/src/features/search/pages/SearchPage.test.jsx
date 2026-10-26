import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { SearchPage } from './SearchPage';

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn() }),
  Toaster: () => null,
}));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

const RESPONSE = {
  search_id: 's-1',
  query: 'a person in a red top',
  mode: 'fast',
  kind: 'text',
  profile: 'local',
  results: [],
  timings_ms: { total: 10 },
  notes: [],
};

const CAMERAS = {
  items: [{ id: 'c1', code: 'cam02', name: 'Gate', enabled: true }],
  next_cursor: null,
};

function render(route) {
  stubApi(apiClient, {
    'POST /search': RESPONSE,
    'GET /cameras': CAMERAS,
    'GET /auth/me': signedInAs('operator'),
  });
  return renderWithProviders(<SearchPage />, { route });
}

const searchBodies = () =>
  vi
    .mocked(apiClient.post)
    .mock.calls.filter(([p]) => p === '/search')
    .map(([, body]) => body);

describe('SearchPage with a camera and a period from the timeline', () => {
  beforeEach(() => {
    clearTokens();
    signedInAs('operator');
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.get).mockReset();
  });

  const ROUTE = '/search?camera=cam02&start=2026-10-25T09:30:00.000Z&end=2026-10-25T09:45:00.000Z';

  it('says which period it will search, and searches only that period on that camera', async () => {
    render(ROUTE);
    expect(await screen.findByText(/Only footage from/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('Describe what to find'), 'a person in a red top');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchBodies().length).toBeGreaterThan(0));
    expect(searchBodies()[0].filters).toEqual({
      cameras: ['cam02'],
      start: '2026-10-25T09:30:00.000Z',
      end: '2026-10-25T09:45:00.000Z',
    });
  });

  it('goes back to the presets when the period is cleared', async () => {
    render(ROUTE);
    await userEvent.click(await screen.findByRole('button', { name: 'Search all times' }));

    expect(screen.queryByText(/Only footage from/)).toBeNull();
    await userEvent.type(screen.getByLabelText('Describe what to find'), 'a person in a red top');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchBodies().length).toBeGreaterThan(0));
    expect(searchBodies()[0].filters.start).toBeNull();
    expect(searchBodies()[0].filters.cameras).toEqual(['cam02']);
  });

  it('ignores a period that makes no sense', async () => {
    render('/search?start=2026-10-25T10:00:00Z&end=2026-10-25T09:00:00Z');
    await screen.findByLabelText('Describe what to find');
    expect(screen.queryByText(/Only footage from/)).toBeNull();
  });

  it('is an ordinary search page without a link', async () => {
    render('/search');
    await screen.findByLabelText('Describe what to find');
    expect(screen.queryByText(/Only footage from/)).toBeNull();
  });
});
