import { describe, expect, it } from 'vitest';
import { ApiError } from './apiClient';
import { errorMessage } from './errorMessage';

const words = { forbidden: 'Only admins can do this.', fallback: 'Could not do it. Try again.' };

describe('errorMessage', () => {
  it.each([400, 404, 409, 422])('passes the api’s own message through for a %i', (status) => {
    expect(
      errorMessage(new ApiError('Polygon points must be normalised.', { status }), words),
    ).toBe('Polygon points must be normalised.');
  });

  it('uses the caller’s wording for a 403, whatever the api said', () => {
    expect(errorMessage(new ApiError('Forbidden', { status: 403 }), words)).toBe(words.forbidden);
  });

  it('uses the fallback for a server error, a network failure and a non-error', () => {
    expect(errorMessage(new ApiError('boom', { status: 500 }), words)).toBe(words.fallback);
    expect(errorMessage(new TypeError('Failed to fetch'), words)).toBe(words.fallback);
    expect(errorMessage(undefined, words)).toBe(words.fallback);
  });

  it('falls back when a 4xx arrives with no message', () => {
    expect(errorMessage(new ApiError('', { status: 409 }), words)).toBe(words.fallback);
  });
});
