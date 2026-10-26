import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { KeyframeStrip } from './KeyframeStrip';

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn() }),
  Toaster: () => null,
}));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

const URLS = ['http://s3/k0.jpg', 'http://s3/k1.jpg'];

describe('KeyframeStrip', () => {
  beforeEach(() => {
    clearTokens();
    signedInAs('operator');
    vi.mocked(apiClient.post).mockReset();
  });

  it('offers nothing to search from when the page does not know the event', () => {
    renderWithProviders(<KeyframeStrip urls={URLS} count={2} camera="cam02" />);
    expect(screen.queryByRole('button', { name: /Find similar/ })).toBeNull();
  });

  it('opens the dialog on the keyframe that was chosen, named by event and position', async () => {
    renderWithProviders(<KeyframeStrip urls={URLS} count={2} camera="cam02" eventId="ev-1" />);

    await userEvent.click(
      screen.getByRole('button', { name: 'Find similar to something in keyframe 2' }),
    );

    const dialog = screen.getByRole('dialog', { name: 'Find similar' });
    expect(dialog).toHaveTextContent('Keyframe 2 from cam02');
    expect(screen.getAllByRole('img', { name: 'Keyframe 2 from cam02' }).at(-1)).toHaveAttribute(
      'src',
      URLS[1],
    );
  });

  it('searches from the keyframe it was opened on, not the first one', async () => {
    stubApi(apiClient, {
      'POST /search/image/crop': {
        search_id: 's-1', query: 'part of a frame', mode: 'fast', kind: 'image', profile: 'local',
        results: [], timings_ms: { total: 1 }, notes: [],
      },
      'GET /auth/me': signedInAs('operator'),
    }); // prettier-ignore
    renderWithProviders(<KeyframeStrip urls={URLS} count={2} camera="cam02" eventId="ev-1" />);
    await userEvent.click(
      screen.getByRole('button', { name: 'Find similar to something in keyframe 2' }),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Use the whole frame' }));
    await userEvent.click(screen.getByRole('button', { name: 'Find similar' }));

    await screen.findByText(/Nothing in the archive looks like that/);
    const call = vi.mocked(apiClient.post).mock.calls.find(([p]) => p === '/search/image/crop');
    expect(call[1]).toMatchObject({ event_id: 'ev-1', keyframe_index: 1, bbox: [0, 0, 1, 1] });
  });

  it('closes the dialog again', async () => {
    renderWithProviders(<KeyframeStrip urls={URLS} count={2} camera="cam02" eventId="ev-1" />);
    await userEvent.click(
      screen.getByRole('button', { name: 'Find similar to something in keyframe 1' }),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
