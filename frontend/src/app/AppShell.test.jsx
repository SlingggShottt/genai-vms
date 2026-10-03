import { screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { createLiveSocket } from '@/lib/ws';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { AppShell } from './AppShell';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock('@/lib/ws', () => ({ createLiveSocket: vi.fn() }));

let socket;

function renderShell(role) {
  const user = signedInAs(role);
  stubApi(apiClient, {
    'GET /auth/me': user,
    'GET /alerts': { items: [], next_cursor: null },
  });
  return renderWithProviders(
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<p>the page</p>} />
      </Route>
    </Routes>,
  );
}

const nav = () => screen.getByRole('navigation', { name: 'Primary' });

describe('AppShell', () => {
  beforeEach(() => {
    clearTokens();
    vi.mocked(apiClient.get).mockReset();
    socket = { start: vi.fn(), stop: vi.fn() };
    vi.mocked(createLiveSocket).mockReset().mockReturnValue(socket);
  });

  it('gives an operator the Events page in the nav, the alert tray and the live channel', async () => {
    renderShell('operator');
    await waitFor(() =>
      expect(within(nav()).getByRole('link', { name: 'Events' })).toHaveAttribute(
        'href',
        '/events',
      ),
    );
    expect(within(nav()).getByRole('link', { name: 'Live wall' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Alerts' })).toBeInTheDocument();
    expect(await screen.findByText(/No open alerts/)).toBeInTheDocument();
    expect(createLiveSocket).toHaveBeenCalledTimes(1);
    expect(socket.start).toHaveBeenCalledTimes(1);
    expect(screen.getByText('the page')).toBeInTheDocument();
  });

  it('gives an admin the same', async () => {
    renderShell('admin');
    expect(await within(nav()).findByRole('link', { name: 'Events' })).toBeInTheDocument();
    await waitFor(() => expect(socket.start).toHaveBeenCalled());
  });

  it('shows a viewer no Events item, no alerts and no live channel', async () => {
    renderShell('viewer');
    expect(
      await screen.findByText('Alerts are shown to operators and admins.'),
    ).toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'Events' })).toBeNull();
    expect(within(nav()).getByRole('link', { name: 'Live wall' })).toBeInTheDocument(); // the rest stays
    expect(within(nav()).getByRole('link', { name: 'Playback' })).toBeInTheDocument();
    expect(createLiveSocket).not.toHaveBeenCalled();
  });

  it('stops the live channel when the shell goes away', async () => {
    const { unmount } = renderShell('operator');
    await waitFor(() => expect(socket.start).toHaveBeenCalled());
    unmount();
    expect(socket.stop).toHaveBeenCalledTimes(1);
  });
});
