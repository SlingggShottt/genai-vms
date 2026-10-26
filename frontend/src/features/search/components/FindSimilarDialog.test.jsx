import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { FindSimilarDialog } from './FindSimilarDialog';

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn() }),
  Toaster: () => null,
}));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

const FRAME = {
  imageUrl: 'http://s3/keyframe.jpg',
  label: 'Keyframe 2 from cam02',
  ref: { event_id: 'ev-1', keyframe_index: 1 },
  cameras: ['cam02'],
};

function result(id, camera = 'cam03') {
  return {
    result_id: id,
    camera_id: camera,
    segment_ids: ['seg-1'],
    start_ts: '2026-10-25T09:30:00Z',
    end_ts: '2026-10-25T09:30:10Z',
    score: 0.81,
    fused_score: 0.81,
    keyframe_url: `http://s3/${id}.jpg`,
    crop_urls: [],
  };
}

const RESPONSE = (results) => ({
  search_id: 's-1',
  query: 'part of a frame',
  mode: 'fast',
  kind: 'image',
  profile: 'local',
  results,
  timings_ms: { total: 120 },
  notes: [],
});

const cropCalls = () =>
  vi.mocked(apiClient.post).mock.calls.filter(([path]) => path === '/search/image/crop');

/** The surface is 400 × 200 px at the page's origin, as jsdom has no layout of its own. */
function drag(from, to) {
  const surface = screen.getByTestId('crop-surface');
  vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({
    left: 0, top: 0, width: 400, height: 200, right: 400, bottom: 200, x: 0, y: 0,
  }); // prettier-ignore
  fireEvent.mouseDown(surface, { clientX: from[0], clientY: from[1], button: 0 });
  fireEvent.mouseMove(surface, { clientX: to[0], clientY: to[1] });
  fireEvent.mouseUp(surface, { clientX: to[0], clientY: to[1] });
}

let me;

describe('FindSimilarDialog', () => {
  beforeEach(() => {
    clearTokens();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.get).mockReset();
    me = signedInAs('operator');
  });

  it('renders nothing while there is no frame', () => {
    renderWithProviders(<FindSimilarDialog frame={null} onClose={() => {}} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the frame and asks for a box before it will search', () => {
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);

    expect(screen.getByRole('dialog', { name: 'Find similar' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Keyframe 2 from cam02' })).toHaveAttribute(
      'src',
      FRAME.imageUrl,
    );
    expect(screen.getByRole('button', { name: 'Find similar' })).toBeDisabled();
    expect(screen.getByText('Draw a box to search.')).toBeInTheDocument();
  });

  it('draws the box as the pointer moves and sends it as fractions of the frame', async () => {
    stubApi(apiClient, {
      'POST /search/image/crop': RESPONSE([result('r1')]),
      'GET /auth/me': me,
    });
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);

    drag([100, 50], [300, 150]);

    const box = screen.getByTestId('crop-box');
    expect(box).toHaveStyle({ left: '25%', top: '25%', width: '50%', height: '50%' });
    await userEvent.click(screen.getByRole('button', { name: 'Find similar' }));

    await waitFor(() => expect(cropCalls()).toHaveLength(1));
    expect(cropCalls()[0][1]).toEqual({
      event_id: 'ev-1',
      keyframe_index: 1,
      bbox: [0.25, 0.25, 0.75, 0.75],
      cameras: ['cam02'],
      top_k: 12,
    });
  });

  it('shows what it found as result cards, without offering to search again from inside', async () => {
    stubApi(apiClient, {
      'POST /search/image/crop': RESPONSE([result('r1', 'cam03'), result('r2', 'cam04')]),
      'GET /auth/me': me,
    });
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);

    drag([100, 50], [300, 150]);
    await userEvent.click(screen.getByRole('button', { name: 'Find similar' }));

    const found = await screen.findByRole('region', { name: 'Similar footage' });
    expect(
      within(found).getByText('2 places where something similar appears.'),
    ).toBeInTheDocument();
    expect(within(found).getAllByRole('article')).toHaveLength(2);
    expect(within(found).queryByRole('button', { name: 'Find similar' })).toBeNull();
  });

  it('says so when nothing looks like it', async () => {
    stubApi(apiClient, { 'POST /search/image/crop': RESPONSE([]), 'GET /auth/me': me });
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: 'Use the whole frame' }));
    await userEvent.click(screen.getByRole('button', { name: 'Find similar' }));

    expect(await screen.findByText(/Nothing in the archive looks like that/)).toBeInTheDocument();
  });

  it('the whole frame can be chosen from the keyboard, and is the box 0,0 to 1,1', async () => {
    stubApi(apiClient, {
      'POST /search/image/crop': RESPONSE([result('r1')]),
      'GET /auth/me': me,
    });
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: 'Use the whole frame' }));
    await userEvent.click(screen.getByRole('button', { name: 'Find similar' }));

    await waitFor(() => expect(cropCalls()).toHaveLength(1));
    expect(cropCalls()[0][1].bbox).toEqual([0, 0, 1, 1]);
  });

  it('only the main button draws: a right-click is left to the browser’s menu', () => {
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);
    const surface = screen.getByTestId('crop-surface');
    vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 400, height: 200, right: 400, bottom: 200, x: 0, y: 0,
    }); // prettier-ignore

    fireEvent.mouseDown(surface, { clientX: 100, clientY: 50, button: 2 });
    fireEvent.mouseMove(surface, { clientX: 300, clientY: 150 });
    fireEvent.mouseUp(surface, { clientX: 300, clientY: 150 });

    expect(screen.queryByTestId('crop-box')).toBeNull();
  });

  it('ignores a click or a sliver: no box, so nothing to search with', () => {
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);

    drag([100, 100], [101, 101]);

    expect(screen.queryByTestId('crop-box')).toBeNull();
    expect(screen.getByRole('button', { name: 'Find similar' })).toBeDisabled();
  });

  it('shows the api’s own words when the frame is gone', async () => {
    stubApi(apiClient, {
      'POST /search/image/crop': new ApiError('That frame is no longer available.', {
        code: 'NOT_FOUND',
        status: 404,
      }),
      'GET /auth/me': me,
    });
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: 'Use the whole frame' }));
    await userEvent.click(screen.getByRole('button', { name: 'Find similar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That frame is no longer available.',
    );
  });

  it('a new box clears the old results, and closing resets the dialog', async () => {
    stubApi(apiClient, {
      'POST /search/image/crop': RESPONSE([result('r1')]),
      'GET /auth/me': me,
    });
    const onClose = vi.fn();
    renderWithProviders(<FindSimilarDialog frame={FRAME} onClose={onClose} />);

    await userEvent.click(screen.getByRole('button', { name: 'Use the whole frame' }));
    await userEvent.click(screen.getByRole('button', { name: 'Find similar' }));
    await screen.findByRole('region', { name: 'Similar footage' });

    drag([10, 10], [200, 100]);
    expect(screen.queryByRole('region', { name: 'Similar footage' })).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });
});
