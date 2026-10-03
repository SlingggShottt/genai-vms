import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { SETTINGS_TABS, SettingsLayout } from './SettingsLayout';
import { router } from './router';

function renderAt(route) {
  return renderWithProviders(
    <Routes>
      <Route path="/settings" element={<SettingsLayout />}>
        <Route path="cameras" element={<p>cameras page</p>} />
        <Route path="zones" element={<p>zones page</p>} />
        <Route path="links" element={<p>links page</p>} />
      </Route>
    </Routes>,
    { route },
  );
}

describe('SettingsLayout', () => {
  it('names the tabs as operators know them', () => {
    expect(SETTINGS_TABS.map((t) => t.label)).toEqual(['Cameras', 'Zones', 'Camera links']);
    renderAt('/settings/cameras');
    const tabs = within(screen.getByRole('navigation', { name: 'Settings' })).getAllByRole('link');
    expect(tabs.map((t) => t.textContent)).toEqual(['Cameras', 'Zones', 'Camera links']);
    expect(tabs.map((t) => t.getAttribute('href'))).toEqual([
      '/settings/cameras',
      '/settings/zones',
      '/settings/links',
    ]);
  });

  it.each([
    ['/settings/cameras', 'Cameras', 'cameras page'],
    ['/settings/zones', 'Zones', 'zones page'],
    ['/settings/links', 'Camera links', 'links page'],
  ])('at %s marks only %s as the current tab and shows its page', (route, current, page) => {
    renderAt(route);
    const nav = screen.getByRole('navigation', { name: 'Settings' });
    const marked = within(nav)
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-current') === 'page');
    expect(marked.map((link) => link.textContent)).toEqual([current]);
    expect(screen.getByText(page)).toBeInTheDocument();
  });
});

describe('the routes', () => {
  const find = (routes, path) => routes.find((r) => r.path === path);

  it('has Settings with a page for cameras, zones and camera links, inside the app shell', () => {
    const protectedRoute = router.routes.find((r) => r.children && !r.path && r.element);
    const shell = protectedRoute.children.find((r) => r.children);
    const settings = find(shell.children, '/settings');
    expect(settings).toBeDefined();
    expect(settings.children.map((r) => r.path ?? 'index')).toEqual([
      'index',
      'cameras',
      'zones',
      'links',
    ]);
  });

  it('sends /settings to the cameras tab', () => {
    const protectedRoute = router.routes.find((r) => r.children && !r.path && r.element);
    const shell = protectedRoute.children.find((r) => r.children);
    const index = find(shell.children, '/settings').children.find((r) => r.index);
    expect(index.element.props).toMatchObject({ to: '/settings/cameras', replace: true });
  });
});
