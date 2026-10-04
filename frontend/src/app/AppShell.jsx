import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { FileText, History, LayoutGrid, ListChecks, Search, Settings, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AlertTray } from '@/features/alerts/components/AlertTray';
import { LiveAlertsProvider } from '@/features/alerts/LiveAlerts';
import { canSeeAlerts } from '@/features/alerts/schemas';
import { useCurrentUser, useLogout } from '@/features/auth/api';
import { cn } from '@/lib/utils';

/** Layout per docs/style_guide.md §B.5: a fixed nav rail, a page header,
 * the routed page as the main work area, and a collapsible alert tray.
 * The timeline dock (playback/investigation) is added by the pages that
 * need it, inside the main work area — it isn't part of the shell itself.
 */
const NAV_ITEMS = [
  { to: '/', label: 'Live wall', icon: LayoutGrid, end: true },
  { to: '/playback', label: 'Playback', icon: History, end: false },
  { to: '/search', label: 'Search', icon: Search, end: false },
  // Alerts and events are for operators and admins (the api answers a viewer with 403).
  { to: '/events', label: 'Events', icon: ListChecks, end: false, needsAlerts: true },
  { to: '/incidents', label: 'Incidents', icon: FileText, end: false },
];

function NavRail() {
  const { data: user } = useCurrentUser();
  const items = NAV_ITEMS.filter((item) => !item.needsAlerts || canSeeAlerts(user));
  return (
    <nav
      aria-label="Primary"
      className="flex w-nav-rail flex-col items-center gap-1 border-r border-rule bg-surface py-3"
    >
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          title={label}
          aria-label={label}
          className={({ isActive }) =>
            cn(
              'flex h-10 w-10 items-center justify-center rounded-panel text-text-muted transition-colors',
              'hover:bg-surface-raised hover:text-text',
              isActive && 'bg-surface-raised text-accent',
            )
          }
        >
          <Icon size={20} aria-hidden="true" />
        </NavLink>
      ))}
      <div className="mt-auto flex flex-col items-center gap-1">
        <NavLink
          to="/settings"
          title="Settings"
          aria-label="Settings"
          className={({ isActive }) =>
            cn(
              'flex h-10 w-10 items-center justify-center rounded-panel text-text-muted transition-colors',
              'hover:bg-surface-raised hover:text-text',
              isActive && 'bg-surface-raised text-accent',
            )
          }
        >
          <Settings size={20} aria-hidden="true" />
        </NavLink>
      </div>
    </nav>
  );
}

function PageHeader() {
  const { data: user } = useCurrentUser();
  const logout = useLogout();

  return (
    <header className="flex h-14 items-center justify-between border-b border-rule bg-surface px-4">
      <div className="text-lg font-semibold text-text">GenAI-VMS</div>
      <div className="flex items-center gap-3">
        {user && <span className="text-sm text-text-muted">{user.full_name}</span>}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          <LogOut size={16} aria-hidden="true" />
          Log out
        </Button>
      </div>
    </header>
  );
}

export function AppShell() {
  const [alertTrayOpen, setAlertTrayOpen] = useState(true);

  return (
    <LiveAlertsProvider>
      <div className="flex h-screen bg-bg">
        <NavRail />
        <div className="flex min-w-0 flex-1 flex-col">
          <PageHeader />
          <main className="flex-1 overflow-auto">
            <Outlet />
          </main>
        </div>
        <AlertTray open={alertTrayOpen} onToggle={() => setAlertTrayOpen((v) => !v)} />
      </div>
    </LiveAlertsProvider>
  );
}
