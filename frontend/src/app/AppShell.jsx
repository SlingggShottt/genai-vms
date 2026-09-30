import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { ChevronRight, History, LayoutGrid, Settings, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
];

function NavRail() {
  return (
    <nav
      aria-label="Primary"
      className="flex w-nav-rail flex-col items-center gap-1 border-r border-rule bg-surface py-3"
    >
      {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
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
          to="/settings/cameras"
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

function AlertTray({ open, onToggle }) {
  return (
    <aside
      aria-label="Alerts"
      className={cn(
        'flex flex-col border-l border-rule bg-surface transition-[width]',
        open ? 'w-alert-tray' : 'w-10',
      )}
    >
      <div className="flex h-14 items-center justify-between border-b border-rule px-3">
        {open && <span className="text-sm font-medium text-text">Alerts</span>}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? 'Collapse alert tray' : 'Expand alert tray'}
          className="flex h-8 w-8 items-center justify-center rounded-panel text-text-muted hover:bg-surface-raised hover:text-text"
        >
          <ChevronRight size={16} className={cn('transition-transform', open && 'rotate-180')} />
        </button>
      </div>
      {open && (
        <div className="flex flex-1 items-center justify-center p-4 text-center text-sm text-text-muted">
          No alerts yet. Alerts appear here once events are detected.
        </div>
      )}
    </aside>
  );
}

export function AppShell() {
  const [alertTrayOpen, setAlertTrayOpen] = useState(true);

  return (
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
  );
}
