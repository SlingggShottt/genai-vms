import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useCurrentUser } from '@/features/auth/api';
import { getRefreshToken } from '@/lib/tokenStore';

export function ProtectedRoute() {
  const location = useLocation();
  // This component stays mounted across navigations between protected
  // routes, so the refresh token can go from present to absent (logout)
  // between renders of the *same* instance — the hook below must always be
  // called (rules-of-hooks), with `enabled` (inside useCurrentUser) doing
  // the actual gating, not an early return before the hook call.
  const hasRefreshToken = Boolean(getRefreshToken());
  const { data: user, isLoading, isError } = useCurrentUser();

  if (!hasRefreshToken) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg text-text-muted">
        Loading…
      </div>
    );
  }

  if (isError || !user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <Outlet />;
}
