import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from './AppShell';
import { ProtectedRoute } from './ProtectedRoute';
import { LoginPage } from '@/features/auth/pages/LoginPage';
import { EventDetailPage } from '@/features/events/pages/EventDetailPage';
import { EventsPage } from '@/features/events/pages/EventsPage';
import { LiveWallPage } from '@/features/live-wall/pages/LiveWallPage';
import { PlaybackPage } from '@/features/playback/pages/PlaybackPage';
import { CamerasSettingsPage } from '@/features/cameras/pages/CamerasSettingsPage';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: '/', element: <LiveWallPage /> },
          { path: '/playback', element: <PlaybackPage /> },
          { path: '/events', element: <EventsPage /> },
          { path: '/events/:alertId', element: <EventDetailPage /> },
          { path: '/settings/cameras', element: <CamerasSettingsPage /> },
        ],
      },
    ],
  },
]);
