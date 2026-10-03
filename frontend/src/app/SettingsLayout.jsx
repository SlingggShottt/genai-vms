import { NavLink, Outlet } from 'react-router-dom';
import { cn } from '@/lib/utils';

// Named as operators know them (style guide §B.8): "Camera links", not "topology edges".
export const SETTINGS_TABS = [
  { to: '/settings/cameras', label: 'Cameras' },
  { to: '/settings/zones', label: 'Zones' },
  { to: '/settings/links', label: 'Camera links' },
];

/** The settings pages share a row of tabs; the routed page is the work area below it. */
export function SettingsLayout() {
  return (
    <div>
      <nav aria-label="Settings" className="flex gap-1 border-b border-rule px-6 pt-3">
        {SETTINGS_TABS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'border-accent text-text'
                  : 'border-transparent text-text-muted hover:text-text',
              )
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
