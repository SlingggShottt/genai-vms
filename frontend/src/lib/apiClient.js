/** Thin fetch wrapper for `/api/v1`: attaches the bearer token, retries once
 * after a transparent refresh on 401, and throws ApiError with the parsed
 * error envelope (docs/style_guide.md §A.5) so callers/UI get `code` and
 * `message` without re-parsing the response.
 */
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from './tokenStore';

const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

export class ApiError extends Error {
  constructor(message, { code, status, details, requestId } = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }
}

// A logged-out user (refresh failed / no refresh token) is signalled with
// this specific subclass so the router can redirect to /login without the
// UI treating it as a generic failed request (e.g. a toast).
export class AuthError extends ApiError {
  constructor(message, opts) {
    super(message, opts);
    this.name = 'AuthError';
  }
}

async function parseErrorBody(response) {
  try {
    const body = await response.json();
    return body?.error;
  } catch {
    return null;
  }
}

function buildUrl(path) {
  if (path.startsWith('http')) return path;
  return `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

// Exported for callers that need the raw URL rather than a parsed JSON
// response — e.g. hls.js loading a playlist directly (features/playback).
export const apiUrl = buildUrl;

async function rawRequest(path, { method = 'GET', body, headers = {}, skipAuth = false } = {}) {
  const finalHeaders = { ...headers };
  // A FormData body (image upload) must keep the multipart boundary the browser generates.
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  if (body !== undefined && !isForm) finalHeaders['Content-Type'] = 'application/json';

  const accessToken = getAccessToken();
  if (!skipAuth && accessToken) {
    finalHeaders.Authorization = `Bearer ${accessToken}`;
  }

  const response = await fetch(buildUrl(path), {
    method,
    headers: finalHeaders,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });

  return response;
}

// Concurrent 401s during one refresh share a single in-flight request
// instead of each firing their own POST /auth/refresh.
let refreshPromise = null;

// Exported for the live WebSocket (lib/ws.js): the server closes a socket with 4401 when its
// access token expires, and the client re-mints one the same way a 401 does.
export async function refreshAccessToken() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) throw new AuthError('Not logged in.');

  if (!refreshPromise) {
    refreshPromise = rawRequest('/auth/refresh', {
      method: 'POST',
      body: { refresh_token: refreshToken },
      skipAuth: true,
    })
      .then(async (response) => {
        if (!response.ok) {
          clearTokens();
          const error = await parseErrorBody(response);
          throw new AuthError(error?.message ?? 'Session expired. Please log in again.', {
            code: error?.code,
            status: response.status,
          });
        }
        const data = await response.json();
        setTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });
        return data.access_token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

/** `path` is relative to `/api/v1` (e.g. `/cameras`). Returns parsed JSON,
 * or `undefined` for a 204. Throws `ApiError` (or `AuthError` when the
 * session itself is gone) on any non-2xx response.
 */
export async function apiRequest(path, options = {}) {
  let response = await rawRequest(path, options);

  if (response.status === 401 && !options.skipAuth && getRefreshToken()) {
    await refreshAccessToken();
    response = await rawRequest(path, options);
  }

  if (response.status === 204) return undefined;

  if (!response.ok) {
    const error = await parseErrorBody(response);
    const ErrorClass = response.status === 401 ? AuthError : ApiError;
    throw new ErrorClass(error?.message ?? `Request failed (${response.status}).`, {
      code: error?.code,
      status: response.status,
      details: error?.details,
      requestId: error?.request_id,
    });
  }

  return response.json();
}

export const apiClient = {
  get: (path, options) => apiRequest(path, { ...options, method: 'GET' }),
  post: (path, body, options) => apiRequest(path, { ...options, method: 'POST', body }),
  patch: (path, body, options) => apiRequest(path, { ...options, method: 'PATCH', body }),
  delete: (path, options) => apiRequest(path, { ...options, method: 'DELETE' }),
};
