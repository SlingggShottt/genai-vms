import { ApiError } from './apiClient';

/** What to tell the person when a request failed: what happened and how to fix it (style guide
 * §B.8), no apologies. The api's own 400/404/409 messages are already written for people, so they
 * pass through; a 403 and anything unexpected get the caller's wording.
 */
export function errorMessage(error, { forbidden, fallback }) {
  if (error instanceof ApiError) {
    if (error.status === 403) return forbidden;
    if ([400, 404, 409, 422].includes(error.status) && error.message) return error.message;
  }
  return fallback;
}
