import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import page from '../fixtures/edges_page.json';
import { CameraLinksPage } from './CameraLinksPage';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const camera = (n) => ({
  id: `01929e6c-0002-7000-8000-00000000000${n}`,
  code: `cam0${n}`,
  name: `Camera ${n}`,
  rtsp_url: 'rtsp://x',
  site_id: 'rvce-campus',
  location_label: null,
  lat: null,
  lon: null,
  enabled: true,
  created_at: '2026-10-01T00:00:00Z',
});
const CAMERAS = { items: [camera(1), camera(2), camera(3)], next_cursor: null };
const [OVERLAP, ONE_WAY] = page.items;

/** A server that keeps its links, so a change is seen when the page refetches. */
function serve({ role = 'admin', cameras = CAMERAS, edges = page.items, ...extra } = {}) {
  let links = [...edges];
  const me = signedInAs(role);
  stubApi(apiClient, {
    'GET /auth/me': me,
    'GET /cameras': cameras,
    'GET /topology/edges': () => ({ items: links }),
    ...extra,
  });
  return {
    set: (next) => {
      links = next;
    },
  };
}

const rowFor = (name) => screen.getByRole('row', { name: new RegExp(name) });
const waitForList = () => screen.findByRole('table');

beforeEach(() => {
  vi.clearAllMocks();
  clearTokens();
});

describe('CameraLinksPage', () => {
  describe('as an admin', () => {
    it('lists the links in words, with their type and timing', async () => {
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      expect(within(rowFor('cam01 ↔ cam02')).getByText('Overlap')).toBeInTheDocument();
      expect(within(rowFor('cam01 ↔ cam02')).getByText('±5 s')).toBeInTheDocument();
      expect(within(rowFor('cam02 → cam03')).getByText('Transit')).toBeInTheDocument();
      expect(within(rowFor('cam02 → cam03')).getByText('10–45 s')).toBeInTheDocument();
      expect(within(rowFor('cam01 ↔ cam03')).getByText('20.5–90 s')).toBeInTheDocument();
    });

    it('draws the diagram beside the list, in the same words', async () => {
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      const diagram = screen.getByRole('img');
      expect(diagram).toHaveAccessibleName(
        expect.stringContaining('cam02 → cam03, transit 10–45 s'),
      );
      expect(screen.getAllByTestId('camera-node')).toHaveLength(3);
    });

    it('adds an overlap link: pick two cameras, set the tolerance, save', async () => {
      const user = userEvent.setup();
      const server = serve();
      apiClient.post.mockImplementationOnce(async (path, body) => {
        server.set([...page.items, { ...OVERLAP, id: 'new', to_camera_id: body.to_camera_id }]);
        return {
          ...OVERLAP,
          id: 'new',
          to_camera_id: body.to_camera_id,
          tolerance_s: body.tolerance_s,
        };
      });
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Add link' }));
      await user.selectOptions(screen.getByLabelText('From camera'), 'Camera 2 (cam02)');
      await user.selectOptions(screen.getByLabelText('To camera'), 'Camera 1 (cam01)');
      const tolerance = screen.getByLabelText('Time tolerance (seconds)');
      expect(tolerance).toHaveValue(5); // the api's default, ready to accept
      await user.clear(tolerance);
      await user.type(tolerance, '8');
      await user.click(screen.getByRole('button', { name: 'Add link' }));

      await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
      expect(apiClient.post).toHaveBeenCalledWith('/topology/edges', {
        from_camera_id: CAMERAS.items[1].id,
        to_camera_id: CAMERAS.items[0].id,
        edge_type: 'overlap',
        tolerance_s: 8,
      });
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Camera link saved'));
      await waitFor(() => expect(screen.queryByLabelText('From camera')).toBeNull()); // the form closes
    });

    it('adds a transit link with a direction', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockResolvedValueOnce({ ...ONE_WAY, id: 'new' });
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Add link' }));
      await user.selectOptions(screen.getByLabelText('From camera'), 'Camera 1 (cam01)');
      await user.selectOptions(screen.getByLabelText('To camera'), 'Camera 2 (cam02)');
      await user.click(screen.getByRole('radio', { name: /Transit/ }));
      expect(screen.queryByLabelText('Time tolerance (seconds)')).toBeNull();
      await user.type(screen.getByLabelText('Shortest trip (seconds)'), '12');
      await user.type(screen.getByLabelText('Longest trip (seconds)'), '60');
      await user.click(screen.getByRole('checkbox', { name: /other way/ }));
      await user.click(screen.getByRole('button', { name: 'Add link' }));

      await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
      expect(apiClient.post).toHaveBeenCalledWith('/topology/edges', {
        from_camera_id: CAMERAS.items[0].id,
        to_camera_id: CAMERAS.items[1].id,
        edge_type: 'transit',
        min_s: 12,
        max_s: 60,
        bidirectional: true,
      });
    });

    it('says what is missing and sends nothing when saved empty', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Add link' }));
      expect(screen.queryByText('Choose the first camera.')).toBeNull(); // not before they try
      await user.click(screen.getByRole('button', { name: 'Add link' }));
      expect(screen.getByText('Choose the first camera.')).toBeInTheDocument();
      expect(screen.getByText('Choose the second camera.')).toBeInTheDocument();
      expect(apiClient.post).not.toHaveBeenCalled();
    });

    it('refuses the same camera twice, and a trip whose longest time is shorter', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Add link' }));
      await user.selectOptions(screen.getByLabelText('From camera'), 'Camera 1 (cam01)');
      await user.selectOptions(screen.getByLabelText('To camera'), 'Camera 1 (cam01)');
      await user.click(screen.getByRole('radio', { name: /Transit/ }));
      await user.type(screen.getByLabelText('Shortest trip (seconds)'), '30');
      await user.type(screen.getByLabelText('Longest trip (seconds)'), '10');
      await user.click(screen.getByRole('button', { name: 'Add link' }));

      expect(screen.getByText('Choose two different cameras.')).toBeInTheDocument();
      expect(
        screen.getByText('The longest trip can’t be shorter than the shortest.'),
      ).toBeInTheDocument();
      expect(apiClient.post).not.toHaveBeenCalled();
    });

    it('shows the api’s reason when it refuses, and keeps the form open', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockRejectedValueOnce(
        new ApiError('An edge between these cameras already exists.', {
          status: 409,
          code: 'CONFLICT',
        }),
      );
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Add link' }));
      await user.selectOptions(screen.getByLabelText('From camera'), 'Camera 1 (cam01)');
      await user.selectOptions(screen.getByLabelText('To camera'), 'Camera 2 (cam02)');
      await user.click(screen.getByRole('button', { name: 'Add link' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'An edge between these cameras already exists.',
      );
      expect(screen.getByLabelText('From camera')).toBeInTheDocument();
      expect(toast.success).not.toHaveBeenCalled();
    });

    it('says something useful when the request fails outright', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockRejectedValueOnce(new TypeError('Failed to fetch'));
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Add link' }));
      await user.selectOptions(screen.getByLabelText('From camera'), 'Camera 1 (cam01)');
      await user.selectOptions(screen.getByLabelText('To camera'), 'Camera 2 (cam02)');
      await user.click(screen.getByRole('button', { name: 'Add link' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Could not save the link. Check your connection and try again.',
      );
    });

    it('edits only the timing: the cameras and type are locked, and only the type’s fields are sent', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.patch.mockResolvedValueOnce({ ...ONE_WAY, max_s: 50 });
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Edit cam02 → cam03' }));
      expect(screen.getByLabelText('From camera')).toBeDisabled();
      expect(screen.getByLabelText('To camera')).toBeDisabled();
      expect(screen.getByRole('radio', { name: /Overlap/ })).toBeDisabled();
      expect(screen.getByRole('radio', { name: /Transit/ })).toBeChecked();
      expect(screen.getByText(/delete this link and add a new one/)).toBeInTheDocument();
      expect(screen.getByLabelText('Shortest trip (seconds)')).toHaveValue(10);
      const longest = screen.getByLabelText('Longest trip (seconds)');
      expect(longest).toHaveValue(45);
      await user.clear(longest);
      await user.type(longest, '50');
      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
      expect(apiClient.patch).toHaveBeenCalledWith(`/topology/edges/${ONE_WAY.id}`, {
        min_s: 10,
        max_s: 50,
        bidirectional: false,
      });
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Camera link saved'));
    });

    it('lights up the link being edited in the diagram', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      expect(screen.getAllByTestId(/^link-/).every((g) => g.dataset.selected === 'false')).toBe(
        true,
      );
      await user.click(screen.getByRole('button', { name: 'Edit cam02 → cam03' }));
      expect(
        screen.getAllByTestId(/^link-/).filter((g) => g.dataset.selected === 'true'),
      ).toHaveLength(1);
    });

    it('does not let a second edit start while one is open', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      await user.click(screen.getByRole('button', { name: 'Edit cam02 → cam03' }));
      expect(screen.getByRole('button', { name: 'Edit cam01 ↔ cam02' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Delete cam01 ↔ cam02' })).toBeDisabled();
      expect(screen.queryByRole('button', { name: 'Add link' })).toBeNull();
    });

    it('drops what was typed when cancelled', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      await user.click(screen.getByRole('button', { name: 'Add link' }));
      await user.selectOptions(screen.getByLabelText('From camera'), 'Camera 3 (cam03)');
      await user.click(screen.getByRole('button', { name: 'Cancel' }));
      await user.click(screen.getByRole('button', { name: 'Add link' }));
      expect(screen.getByLabelText('From camera')).toHaveValue('');
    });

    it('asks first, then deletes, and the list refreshes', async () => {
      const user = userEvent.setup();
      const server = serve();
      apiClient.delete.mockImplementationOnce(async () => {
        server.set(page.items.filter((e) => e.id !== ONE_WAY.id));
      });
      renderWithProviders(<CameraLinksPage />);
      await waitForList();

      await user.click(screen.getByRole('button', { name: 'Delete cam02 → cam03' }));
      const dialog = await screen.findByRole('dialog', { name: 'Delete camera link' });
      expect(dialog).toHaveTextContent('Delete the link cam02 → cam03?');
      expect(apiClient.delete).not.toHaveBeenCalled();
      await user.click(within(dialog).getByRole('button', { name: 'Delete link' }));

      await waitFor(() =>
        expect(apiClient.delete).toHaveBeenCalledWith(`/topology/edges/${ONE_WAY.id}`),
      );
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Camera link deleted'));
      await waitFor(() => expect(screen.queryByRole('row', { name: /cam02 → cam03/ })).toBeNull());
      expect(screen.queryByRole('dialog')).toBeNull();
    });

    it('deletes nothing if the question is cancelled', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      await user.click(screen.getByRole('button', { name: 'Delete cam02 → cam03' }));
      await user.click(
        within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }),
      );
      expect(apiClient.delete).not.toHaveBeenCalled();
      expect(screen.getByRole('row', { name: /cam02 → cam03/ })).toBeInTheDocument();
    });

    it('keeps the dialog open and says why when the delete fails', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.delete.mockRejectedValueOnce(new ApiError('Boom', { status: 500 }));
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      await user.click(screen.getByRole('button', { name: 'Delete cam02 → cam03' }));
      const dialog = await screen.findByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: 'Delete link' }));
      expect(await within(dialog).findByRole('alert')).toHaveTextContent(
        'Could not delete the link. Check your connection and try again.',
      );
      expect(toast.success).not.toHaveBeenCalled();
    });

    it('invites the first link when there are none', async () => {
      serve({ edges: [] });
      renderWithProviders(<CameraLinksPage />);
      expect(await screen.findByText(/No camera links yet. Add a link/)).toBeInTheDocument();
      expect(screen.queryByRole('table')).toBeNull();
      expect(screen.getByRole('img')).toHaveAccessibleName('Camera links diagram: no links yet.');
    });

    it('shows an unknown camera as such, rather than failing', async () => {
      serve({ cameras: { items: CAMERAS.items.slice(0, 2), next_cursor: null } }); // cam03 is gone
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      expect(rowFor('cam02 → unknown camera')).toBeInTheDocument();
    });
  });

  describe('with fewer than two cameras', () => {
    it('explains that a link needs two, and offers no form', async () => {
      serve({ cameras: { items: [camera(1)], next_cursor: null }, edges: [] });
      renderWithProviders(<CameraLinksPage />);
      expect(await screen.findByText(/Add at least two cameras first/)).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Add link' })).toBeNull();
    });
  });

  describe('as someone who is not an admin', () => {
    it.each(['operator', 'viewer'])(
      'shows a %s the links but no way to change them',
      async (role) => {
        serve({ role });
        renderWithProviders(<CameraLinksPage />);
        await waitForList();
        expect(rowFor('cam02 → cam03')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Add link' })).toBeNull();
        expect(screen.queryByRole('button', { name: /^Edit / })).toBeNull();
        expect(screen.queryByRole('button', { name: /^Delete / })).toBeNull();
        expect(screen.queryByRole('columnheader', { name: 'Actions' })).toBeNull();
        expect(screen.getByText('Only admins can change camera links.')).toBeInTheDocument();
      },
    );
  });

  describe('loading and failing', () => {
    it('says so while loading', () => {
      stubApi(apiClient, {
        'GET /auth/me': signedInAs('admin'),
        'GET /cameras': () => new Promise(() => {}),
        'GET /topology/edges': () => new Promise(() => {}),
      });
      renderWithProviders(<CameraLinksPage />);
      expect(screen.getByText('Loading camera links…')).toBeInTheDocument();
    });

    it('says so when the links cannot be loaded', async () => {
      stubApi(apiClient, {
        'GET /auth/me': signedInAs('admin'),
        'GET /cameras': CAMERAS,
        'GET /topology/edges': new ApiError('Boom', { status: 500 }),
      });
      renderWithProviders(<CameraLinksPage />);
      expect(await screen.findByText('Could not load camera links.')).toBeInTheDocument();
    });
  });

  describe('what is shown when', () => {
    it('shows no table or diagram with only one camera', async () => {
      serve({ cameras: { items: [camera(1)], next_cursor: null }, edges: [] });
      renderWithProviders(<CameraLinksPage />);
      await screen.findByText(/Add at least two cameras first/);
      expect(screen.queryByRole('table')).toBeNull();
      expect(screen.queryByRole('img')).toBeNull();
    });

    it('keeps saying it is loading until the cameras and the links are both in', async () => {
      stubApi(apiClient, {
        'GET /auth/me': signedInAs('admin'),
        'GET /cameras': CAMERAS,
        'GET /topology/edges': () => new Promise(() => {}), // never answers
      });
      const { queryClient } = renderWithProviders(<CameraLinksPage />);
      await waitFor(() => expect(queryClient.getQueryData(['cameras'])).toBeDefined());
      expect(screen.getByText('Loading camera links…')).toBeInTheDocument();
      expect(screen.queryByText(/No camera links yet/)).toBeNull(); // not "none" while still asking
    });

    it('shows that it is saving, and cannot be pressed again or cancelled meanwhile', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockReturnValueOnce(new Promise(() => {}));
      renderWithProviders(<CameraLinksPage />);
      await waitForList();
      await user.click(screen.getByRole('button', { name: 'Add link' }));
      await user.selectOptions(screen.getByLabelText('From camera'), 'Camera 1 (cam01)');
      await user.selectOptions(screen.getByLabelText('To camera'), 'Camera 2 (cam02)');
      await user.click(screen.getByRole('button', { name: 'Add link' }));

      expect(await screen.findByRole('button', { name: 'Saving…' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    });
  });
});
