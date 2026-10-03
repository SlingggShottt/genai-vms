import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { renderWithProviders, signedInAs, stubApi } from '@/test/utils';
import { NoPictureError, captureFrame } from '../captureFrame';
import page from '../fixtures/zones_page.json';
import { ZonesPage } from './ZonesPage';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
// The live view needs WebRTC/HLS; the test only needs a <video> the capture can be pointed at.
vi.mock('@/components/VideoTile', () => ({
  VideoTile: ({ camera, videoElRef }) => (
    // eslint-disable-next-line jsx-a11y/media-has-caption -- a stand-in for live CCTV, which has no captions
    <video data-testid="live-view" aria-label={camera.name} ref={videoElRef} />
  ),
}));
vi.mock('../captureFrame', async (importOriginal) => ({
  ...(await importOriginal()),
  captureFrame: vi.fn(),
}));

const CAM1 = '01929e6c-0002-7000-8000-000000000001';
const CAM2 = '01929e6c-0002-7000-8000-000000000002';
const camera = (id, code, name) => ({
  id,
  code,
  name,
  rtsp_url: 'rtsp://x',
  site_id: 'rvce-campus',
  location_label: null,
  lat: null,
  lon: null,
  enabled: true,
  created_at: '2026-10-01T00:00:00Z',
});
const CAMERAS = {
  items: [camera(CAM1, 'cam01', 'North gate'), camera(CAM2, 'cam02', 'Library')],
  next_cursor: null,
};
const [BAY, YARD] = page.items;

const RECT = { left: 0, top: 0, width: 400, height: 225, right: 400, bottom: 225, x: 0, y: 0 };

function serve({ role = 'admin', cameras = CAMERAS, zones = {} } = {}) {
  stubApi(apiClient, {
    'GET /auth/me': signedInAs(role),
    'GET /cameras': cameras,
    'GET /cameras/status': { cameras: [] },
    [`GET /cameras/${CAM1}/zones`]: page,
    [`GET /cameras/${CAM2}/zones`]: { items: [] },
    ...zones,
  });
}

const canvas = () => screen.getByTestId('zone-canvas');
const clickFrame = (x, y) => fireEvent.click(canvas(), { clientX: x, clientY: y });
const handles = () => screen.queryAllByRole('button', { name: /^Point \d+ of \d+/ });

/** Opens the editor on a captured frame. */
async function captureAFrame(user) {
  await user.click(screen.getByRole('button', { name: 'Capture frame' }));
  await screen.findByAltText('Camera frame to draw the zone on');
}

async function draw(user, points) {
  for (const [x, y] of points) clickFrame(x, y);
  await waitFor(() => expect(handles()).toHaveLength(points.length));
}

const TRIANGLE_CLICKS = [
  [80, 45],
  [320, 45],
  [200, 200],
];
const TRIANGLE = [
  [0.2, 0.2],
  [0.8, 0.2],
  [0.5, 0.8889],
];

let urls;
beforeEach(() => {
  vi.clearAllMocks();
  clearTokens();
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(RECT);
  urls = 0;
  URL.createObjectURL = vi.fn(() => `blob:frame-${(urls += 1)}`);
  URL.revokeObjectURL = vi.fn();
  captureFrame.mockResolvedValue({ blob: new Blob(['jpeg']), width: 1280, height: 720 });
});

describe('ZonesPage', () => {
  describe('the list', () => {
    it('shows the first camera’s zones: type, points and normal hours', async () => {
      serve();
      renderWithProviders(<ZonesPage />);
      const list = await screen.findByRole('list');
      const items = within(list).getAllByRole('listitem');
      expect(items).toHaveLength(2);
      expect(items[0]).toHaveTextContent('Loading bay');
      expect(items[0]).toHaveTextContent('General · 4 points');
      expect(items[0]).toHaveTextContent('Normal hours: Always');
      expect(items[1]).toHaveTextContent('Staff yard');
      expect(items[1]).toHaveTextContent('Restricted · 3 points');
      expect(items[1]).toHaveTextContent('Normal hours: 22:00–06:00, weekdays');
      expect(screen.getByRole('heading', { name: 'Zones on North gate' })).toBeInTheDocument();
    });

    it('switches camera, and starts clean on the new one', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await captureAFrame(user);

      await user.selectOptions(screen.getByLabelText('Camera'), 'Library (cam02)');

      expect(await screen.findByText(/No zones yet. Add a zone/)).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Zones on Library' })).toBeInTheDocument();
      expect(screen.queryByAltText('Camera frame to draw the zone on')).toBeNull(); // the frame is gone
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:frame-1'); // and freed
    });

    it('opens on the camera named in the address', async () => {
      serve();
      renderWithProviders(<ZonesPage />, { route: `/?camera=${CAM2}` });
      expect(await screen.findByRole('heading', { name: 'Zones on Library' })).toBeInTheDocument();
      expect(screen.getByLabelText('Camera')).toHaveValue(CAM2);
    });

    it('falls back to the first camera when the address names one that does not exist', async () => {
      serve();
      renderWithProviders(<ZonesPage />, { route: '/?camera=nonsense' });
      expect(
        await screen.findByRole('heading', { name: 'Zones on North gate' }),
      ).toBeInTheDocument();
    });

    it('says what to do when there are no cameras', async () => {
      serve({ cameras: { items: [], next_cursor: null } });
      renderWithProviders(<ZonesPage />);
      expect(
        await screen.findByText('No cameras yet. Add a camera before drawing zones.'),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText('Camera')).toBeNull();
    });

    it('says so when the zones cannot be loaded', async () => {
      serve({ zones: { [`GET /cameras/${CAM1}/zones`]: new ApiError('Boom', { status: 500 }) } });
      renderWithProviders(<ZonesPage />);
      expect(await screen.findByText('Could not load zones.')).toBeInTheDocument();
    });
  });

  describe('drawing a zone', () => {
    it('captures a frame from the live view, then saves the outline, name and type', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockResolvedValueOnce({ ...BAY, id: 'new', name: 'Gate' });
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');

      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      expect(
        screen.getByText('Capture a frame first, then draw the outline on it.'),
      ).toBeInTheDocument();
      await captureAFrame(user);
      // It is given the live view's <video>, which is what the picture is taken from.
      expect(captureFrame).toHaveBeenCalledWith(expect.any(HTMLVideoElement));
      expect(screen.getByAltText('Camera frame to draw the zone on')).toHaveAttribute(
        'src',
        'blob:frame-1',
      );

      await draw(user, TRIANGLE_CLICKS);
      await user.type(screen.getByLabelText('Name'), '  Gate ');
      await user.selectOptions(screen.getByLabelText('Type'), 'Entrance');
      await user.click(screen.getByRole('button', { name: 'Save zone' }));

      await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
      expect(apiClient.post).toHaveBeenCalledWith(`/cameras/${CAM1}/zones`, {
        name: 'Gate',
        zone_type: 'entrance',
        polygon: TRIANGLE,
        schedule: null,
      });
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Zone saved'));
      await waitFor(() => expect(screen.queryByLabelText('Name')).toBeNull()); // the form closes
      expect(handles()).toHaveLength(0); // and the outline is cleared
    });

    it('sets normal hours: times, and the days that are ticked', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockResolvedValueOnce({ ...YARD, id: 'new' });
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');

      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      await captureAFrame(user);
      await draw(user, TRIANGLE_CLICKS);
      await user.type(screen.getByLabelText('Name'), 'Yard');
      await user.click(screen.getByRole('checkbox', { name: 'Set normal hours' }));
      fireEvent.change(screen.getByLabelText('From'), { target: { value: '22:00' } });
      fireEvent.change(screen.getByLabelText('To'), { target: { value: '06:00' } });
      await user.click(screen.getByRole('checkbox', { name: 'Sat' }));
      await user.click(screen.getByRole('checkbox', { name: 'Sun' }));
      await user.click(screen.getByRole('button', { name: 'Save zone' }));

      await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
      expect(apiClient.post.mock.calls[0][1].schedule).toEqual({
        start_time: '22:00',
        end_time: '06:00',
        days: ['mon', 'tue', 'wed', 'thu', 'fri'],
      });
    });

    it('says what is missing and sends nothing when saved empty', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');

      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      expect(screen.queryByText('Enter a name for the zone.')).toBeNull(); // not before they try
      await user.click(screen.getByRole('button', { name: 'Save zone' }));

      expect(screen.getByText('Enter a name for the zone.')).toBeInTheDocument();
      expect(screen.getByText('Add at least 3 points to outline the zone.')).toBeInTheDocument();
      expect(apiClient.post).not.toHaveBeenCalled();
    });

    it('refuses a crossing outline, and says how to fix it', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      await captureAFrame(user);
      await draw(user, [
        [80, 45],
        [320, 180],
        [320, 45],
        [80, 180],
      ]);
      await user.type(screen.getByLabelText('Name'), 'Knot');
      await user.click(screen.getByRole('button', { name: 'Save zone' }));
      expect(screen.getByRole('alert')).toHaveTextContent(
        "The outline crosses itself. Move a point so the edges don't cross.",
      );
      expect(apiClient.post).not.toHaveBeenCalled();
    });

    it('shows the api’s reason when it refuses, and keeps the drawing', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockRejectedValueOnce(
        new ApiError('Polygon must have between 3 and 32 points.', { status: 400 }),
      );
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      await captureAFrame(user);
      await draw(user, TRIANGLE_CLICKS);
      await user.type(screen.getByLabelText('Name'), 'Gate');
      await user.click(screen.getByRole('button', { name: 'Save zone' }));

      expect(
        await screen.findByText('Polygon must have between 3 and 32 points.'),
      ).toBeInTheDocument();
      expect(handles()).toHaveLength(3);
      expect(screen.getByLabelText('Name')).toHaveValue('Gate');
      expect(toast.success).not.toHaveBeenCalled();
    });

    it('says something useful when the request fails outright', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockRejectedValueOnce(new TypeError('Failed to fetch'));
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      await captureAFrame(user);
      await draw(user, TRIANGLE_CLICKS);
      await user.type(screen.getByLabelText('Name'), 'Gate');
      await user.click(screen.getByRole('button', { name: 'Save zone' }));
      expect(
        await screen.findByText('Could not save the zone. Check your connection and try again.'),
      ).toBeInTheDocument();
    });

    it('explains why a frame could not be captured', async () => {
      const user = userEvent.setup();
      serve();
      captureFrame.mockRejectedValueOnce(
        new NoPictureError('No picture yet. Wait for the stream to start, then capture again.'),
      );
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Capture frame' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'No picture yet. Wait for the stream to start',
      );
      expect(screen.queryByAltText('Camera frame to draw the zone on')).toBeNull();
    });

    it('can capture a new frame, keeping the outline, and frees the old picture', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      await captureAFrame(user);
      await draw(user, TRIANGLE_CLICKS);

      await user.click(screen.getByRole('button', { name: 'Capture a new frame' }));
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:frame-1');
      await captureAFrame(user);
      expect(screen.getByAltText('Camera frame to draw the zone on')).toHaveAttribute(
        'src',
        'blob:frame-2',
      );
      expect(handles()).toHaveLength(3);
    });

    it('drops the drawing when cancelled, so the next zone starts blank', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      await captureAFrame(user);
      await draw(user, TRIANGLE_CLICKS);
      await user.type(screen.getByLabelText('Name'), 'Gate');
      await user.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(screen.queryByLabelText('Name')).toBeNull();
      expect(handles()).toHaveLength(0);

      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      expect(screen.getByLabelText('Name')).toHaveValue('');
      expect(handles()).toHaveLength(0);
    });

    it('lets the frame be looked at, but not drawn on, when no zone is being added', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await captureAFrame(user);
      expect(
        screen.getByText('Add a zone, or edit one, to draw on this frame.'),
      ).toBeInTheDocument();
      clickFrame(100, 45);
      expect(handles()).toHaveLength(0);
      // The camera's zones are drawn on it for context.
      expect(
        within(screen.getByRole('region', { name: 'Camera frame' })).getByText('Staff yard'),
      ).toBeInTheDocument();
    });
  });

  describe('editing a zone', () => {
    it('opens with the zone’s details, draws its outline once a frame is captured, and saves a patch', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.patch.mockResolvedValueOnce({ ...BAY, name: 'Loading dock' });
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');

      await user.click(screen.getByRole('button', { name: 'Edit Loading bay' }));
      expect(screen.getByLabelText('Name')).toHaveValue('Loading bay');
      expect(screen.getByLabelText('Type')).toHaveValue('generic');
      expect(screen.getByRole('checkbox', { name: 'Set normal hours' })).not.toBeChecked();
      await captureAFrame(user);
      expect(handles()).toHaveLength(4);
      // The zone being edited is not also drawn as "another zone"; the other one is.
      const frame = within(screen.getByRole('region', { name: 'Camera frame' }));
      expect(frame.queryByText('Loading bay')).toBeNull();
      expect(frame.getByText('Staff yard')).toBeInTheDocument();

      const name = screen.getByLabelText('Name');
      await user.clear(name);
      await user.type(name, 'Loading dock');
      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
      expect(apiClient.patch).toHaveBeenCalledWith(`/zones/${BAY.id}`, {
        name: 'Loading dock',
        zone_type: 'generic',
        polygon: BAY.polygon,
        schedule: null,
      });
      expect(apiClient.post).not.toHaveBeenCalled();
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Zone saved'));
    });

    it('opens a zone with normal hours switched on, and turning them off sends a null schedule', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.patch.mockResolvedValueOnce({ ...YARD, schedule: null });
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');

      await user.click(screen.getByRole('button', { name: 'Edit Staff yard' }));
      expect(screen.getByRole('checkbox', { name: 'Set normal hours' })).toBeChecked();
      expect(screen.getByLabelText('From')).toHaveValue('22:00');
      expect(screen.getByLabelText('To')).toHaveValue('06:00');
      expect(screen.getByRole('checkbox', { name: 'Mon' })).toBeChecked();
      expect(screen.getByRole('checkbox', { name: 'Sat' })).not.toBeChecked();
      await user.click(screen.getByRole('checkbox', { name: 'Set normal hours' }));
      await captureAFrame(user);
      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
      expect(apiClient.patch.mock.calls[0][1].schedule).toBeNull();
    });

    it('does not let another zone be edited or deleted meanwhile', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Edit Loading bay' }));
      expect(screen.getByRole('button', { name: 'Edit Staff yard' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Delete Staff yard' })).toBeDisabled();
      expect(screen.queryByRole('button', { name: 'Add zone' })).toBeNull();
    });
  });

  describe('deleting a zone', () => {
    it('asks first, then deletes, and the list refreshes', async () => {
      const user = userEvent.setup();
      let items = page.items;
      serve({ zones: { [`GET /cameras/${CAM1}/zones`]: () => ({ items }) } });
      apiClient.delete.mockImplementationOnce(async () => {
        items = items.filter((z) => z.id !== YARD.id);
      });
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');

      await user.click(screen.getByRole('button', { name: 'Delete Staff yard' }));
      const dialog = await screen.findByRole('dialog', { name: 'Delete zone' });
      expect(dialog).toHaveTextContent(
        "Delete “Staff yard” from North gate? This can't be undone.",
      );
      expect(apiClient.delete).not.toHaveBeenCalled();
      await user.click(within(dialog).getByRole('button', { name: 'Delete zone' }));

      await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith(`/zones/${YARD.id}`));
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Zone deleted'));
      await waitFor(() => expect(screen.queryByText('Staff yard')).toBeNull());
    });

    it('deletes nothing if the question is cancelled', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Delete Staff yard' }));
      await user.click(
        within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }),
      );
      expect(apiClient.delete).not.toHaveBeenCalled();
      expect(screen.getByText('Staff yard')).toBeInTheDocument();
    });

    it('keeps the question open and says why when the delete is refused', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.delete.mockRejectedValueOnce(new ApiError('Forbidden', { status: 403 }));
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Delete Staff yard' }));
      const dialog = await screen.findByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: 'Delete zone' }));
      expect(await within(dialog).findByRole('alert')).toHaveTextContent(
        'Only admins can delete zones.',
      );
      expect(toast.success).not.toHaveBeenCalled();
    });
  });

  describe('as someone who is not an admin', () => {
    it.each(['operator', 'viewer'])(
      'shows a %s the zones and nothing to change them with',
      async (role) => {
        serve({ role });
        renderWithProviders(<ZonesPage />);
        expect(await screen.findByText('Staff yard')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Add zone' })).toBeNull();
        expect(screen.queryByRole('button', { name: /^Edit / })).toBeNull();
        expect(screen.queryByRole('button', { name: /^Delete / })).toBeNull();
        expect(screen.queryByRole('button', { name: 'Capture frame' })).toBeNull();
        expect(screen.queryByTestId('live-view')).toBeNull();
        expect(screen.getByText('Only admins can change zones.')).toBeInTheDocument();
      },
    );

    it('says plainly when the camera has no zones', async () => {
      serve({ role: 'viewer' });
      renderWithProviders(<ZonesPage />, { route: `/?camera=${CAM2}` });
      expect(await screen.findByText('No zones on this camera yet.')).toBeInTheDocument();
    });
  });

  describe('what the form tells you, and when', () => {
    it('does not scold before the first attempt, then explains once there has been one', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      expect(
        screen.getByText('Draw the outline on the frame, then name the zone.'),
      ).toBeInTheDocument();
      expect(screen.queryByText('Add at least 3 points to outline the zone.')).toBeNull();

      await user.click(screen.getByRole('button', { name: 'Save zone' }));
      expect(screen.getByText('Add at least 3 points to outline the zone.')).toBeInTheDocument();
      expect(screen.queryByText('Draw the outline on the frame, then name the zone.')).toBeNull();
    });

    it('shows that it is saving, and cannot be pressed again or cancelled meanwhile', async () => {
      const user = userEvent.setup();
      serve();
      apiClient.post.mockReturnValueOnce(new Promise(() => {}));
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Add zone' }));
      await captureAFrame(user);
      await draw(user, TRIANGLE_CLICKS);
      await user.type(screen.getByLabelText('Name'), 'Gate');
      await user.click(screen.getByRole('button', { name: 'Save zone' }));

      expect(await screen.findByRole('button', { name: 'Saving…' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    });

    it('shapes the frame like the picture that was captured', async () => {
      const user = userEvent.setup();
      serve();
      captureFrame.mockResolvedValueOnce({ blob: new Blob(['jpeg']), width: 640, height: 480 });
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await captureAFrame(user);
      const frame = screen.getByRole('region', { name: 'Camera frame' });
      expect(frame.querySelector('[style*="aspect-ratio"]')).toHaveStyle({
        aspectRatio: String(640 / 480),
      });
    });

    it('marks the zone being edited in the list, and no other', async () => {
      const user = userEvent.setup();
      serve();
      renderWithProviders(<ZonesPage />);
      await screen.findByRole('list');
      await user.click(screen.getByRole('button', { name: 'Edit Loading bay' }));
      expect(screen.getByText('Loading bay').closest('li')).toHaveClass('bg-surface-raised');
      expect(screen.getByText('Staff yard').closest('li')).not.toHaveClass('bg-surface-raised');
    });
  });
});
