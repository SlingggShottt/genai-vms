/** Refresh token persists across reloads (localStorage); the access token
 * lives only in memory so a page that can run arbitrary script (XSS) can't
 * read it back out of storage — it's re-minted from the refresh token on
 * load instead. See lib/apiClient.js for the refresh flow.
 */
const REFRESH_TOKEN_KEY = 'vms.refresh_token';

let accessToken = null;

export function getAccessToken() {
  return accessToken;
}

export function getRefreshToken() {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setTokens({ accessToken: nextAccessToken, refreshToken }) {
  accessToken = nextAccessToken;
  try {
    if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  } catch {
    // Private-mode/blocked storage: refresh token just won't survive a reload.
  }
}

export function clearTokens() {
  accessToken = null;
  try {
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  } catch {
    // ignore
  }
}
