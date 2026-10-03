import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { setTokens } from '@/lib/tokenStore';

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

/** Render with a fresh QueryClient and a router. Returns the client too, to read caches. */
export function renderWithProviders(ui, { route = '/', queryClient = makeQueryClient() } = {}) {
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

/** Sign in as `role` for the tests: a refresh token (so `useCurrentUser` runs) and the user
 * `/auth/me` returns.
 */
export function signedInAs(role) {
  setTokens({ accessToken: 'access', refreshToken: 'refresh' });
  return {
    id: `user-${role}`,
    email: `${role}@example.com`,
    full_name: role,
    role,
    is_active: true,
    created_at: '2026-10-01T00:00:00Z',
  };
}

/**
 * Route `apiClient` calls to canned answers by path (query string ignored). `routes` maps
 * `'GET /alerts'` -> value or `(path, body) => value`; an `Error` instance is thrown.
 * Anything unlisted fails loudly, so a test never silently talks to nothing.
 */
export function stubApi(apiClient, routes) {
  const answer = (method) =>
    vi.fn(async (path, maybeBody) => {
      const key = `${method} ${path.split('?')[0]}`;
      if (!(key in routes)) throw new Error(`unexpected api call: ${method} ${path}`);
      const handler = routes[key];
      const value = typeof handler === 'function' ? handler(path, maybeBody) : handler;
      if (value instanceof Error) throw value;
      return value;
    });
  apiClient.get.mockImplementation(answer('GET'));
  apiClient.post.mockImplementation(answer('POST'));
  // Tests of pages that edit things mock these two as well; the older ones mock only get/post.
  apiClient.patch?.mockImplementation(answer('PATCH'));
  apiClient.delete?.mockImplementation(answer('DELETE'));
}
