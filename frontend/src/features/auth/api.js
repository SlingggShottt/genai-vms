/** Auth queries/mutations (TanStack Query) — responses validated with zod
 * before reaching components (style_guide.md §A.2).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, AuthError } from '@/lib/apiClient';
import { clearTokens, getRefreshToken, setTokens } from '@/lib/tokenStore';
import { tokenResponseSchema, userSchema } from './schemas';

export const CURRENT_USER_QUERY_KEY = ['auth', 'me'];

async function fetchCurrentUser() {
  const data = await apiClient.get('/auth/me');
  return userSchema.parse(data);
}

/** Only runs while a refresh token exists — `apiClient` transparently mints
 * a fresh access token from it on the first 401 (see lib/apiClient.js), so
 * this is also how the app re-authenticates a returning visitor.
 */
export function useCurrentUser() {
  return useQuery({
    queryKey: CURRENT_USER_QUERY_KEY,
    queryFn: fetchCurrentUser,
    enabled: Boolean(getRefreshToken()),
    retry: (failureCount, error) => !(error instanceof AuthError) && failureCount < 2,
    staleTime: 5 * 60 * 1000,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ email, password }) => {
      const data = await apiClient.post('/auth/login', { email, password }, { skipAuth: true });
      return tokenResponseSchema.parse(data);
    },
    onSuccess: (tokens) => {
      setTokens({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
      queryClient.invalidateQueries({ queryKey: CURRENT_USER_QUERY_KEY });
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const refreshToken = getRefreshToken();
      if (refreshToken) {
        await apiClient.post('/auth/logout', { refresh_token: refreshToken });
      }
    },
    onSettled: () => {
      clearTokens();
      queryClient.setQueryData(CURRENT_USER_QUERY_KEY, null);
      queryClient.clear();
    },
  });
}
