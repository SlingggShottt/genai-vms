import { Navigate, createBrowserRouter } from 'react-router-dom';
import { AppShell } from './AppShell';
import { ProtectedRoute } from './ProtectedRoute';
import { SettingsLayout } from './SettingsLayout';
import { LoginPage } from '@/features/auth/pages/LoginPage';
import { AssistantPage } from '@/features/assistant/pages/AssistantPage';
import { EventDetailPage } from '@/features/events/pages/EventDetailPage';
import { EventsPage } from '@/features/events/pages/EventsPage';
import { IncidentPage } from '@/features/incidents/pages/IncidentPage';
import { IncidentsPage } from '@/features/incidents/pages/IncidentsPage';
import { LiveWallPage } from '@/features/live-wall/pages/LiveWallPage';
import { ReportPage } from '@/features/reports/pages/ReportPage';
import { ReportsPage } from '@/features/reports/pages/ReportsPage';
import { SearchPage } from '@/features/search/pages/SearchPage';
import { PlaybackPage } from '@/features/playback/pages/PlaybackPage';
import { CamerasSettingsPage } from '@/features/cameras/pages/CamerasSettingsPage';
import { CameraLinksPage } from '@/features/topology/pages/CameraLinksPage';
import { ZonesPage } from '@/features/zones/pages/ZonesPage';

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
          { path: '/search', element: <SearchPage /> },
          { path: '/assistant', element: <AssistantPage /> },
          { path: '/assistant/:sessionId', element: <AssistantPage /> },
          { path: '/events', element: <EventsPage /> },
          { path: '/incidents', element: <IncidentsPage /> },
          { path: '/reports', element: <ReportsPage /> },
          { path: '/reports/:reportId', element: <ReportPage /> },
          { path: '/incidents/:incidentId', element: <IncidentPage /> },
          { path: '/events/:alertId', element: <EventDetailPage /> },
          {
            path: '/settings',
            element: <SettingsLayout />,
            children: [
              { index: true, element: <Navigate to="/settings/cameras" replace /> },
              { path: 'cameras', element: <CamerasSettingsPage /> },
              { path: 'zones', element: <ZonesPage /> },
              { path: 'links', element: <CameraLinksPage /> },
            ],
          },
        ],
      },
    ],
  },
]);
