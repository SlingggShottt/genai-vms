import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearTokens, setTokens } from '@/lib/tokenStore';
import { hlsAuthConfig, isPresignedUrl } from './api';

// Same shape services/api puts in the generated playlist: a SigV4
// query-string presigned MinIO URL.
const PRESIGNED_SEGMENT =
  'http://localhost:9000/vms-segments/cam01/2026/10/01/06/cam01_20261001T063437Z_000000.ts' +
  '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=vms-admin%2F20261001%2Fus-east-1%2Fs3%2Faws4_request' +
  '&X-Amz-Date=20261001T063500Z&X-Amz-Expires=900&X-Amz-SignedHeaders=host&X-Amz-Signature=abc123';

const MANIFEST_RELATIVE =
  '/api/v1/recordings/cam01/playlist.m3u8?start=2026-10-01T06%3A34%3A00.000Z&end=2026-10-01T06%3A35%3A00.000Z';
const MANIFEST_ABSOLUTE = `http://localhost:8000${MANIFEST_RELATIVE}`;

function fakeXhr() {
  return { setRequestHeader: vi.fn() };
}

describe('isPresignedUrl', () => {
  it('detects a SigV4 presigned segment URL', () => {
    expect(isPresignedUrl(PRESIGNED_SEGMENT)).toBe(true);
  });

  it('is false for the API manifest URL, relative or absolute', () => {
    expect(isPresignedUrl(MANIFEST_RELATIVE)).toBe(false);
    expect(isPresignedUrl(MANIFEST_ABSOLUTE)).toBe(false);
  });

  it('is false for a URL that merely mentions the parameter name outside the query', () => {
    expect(isPresignedUrl('http://localhost:9000/X-Amz-Signature=/seg.ts')).toBe(false);
  });
});

describe('hlsAuthConfig().xhrSetup', () => {
  beforeEach(() => {
    clearTokens();
  });

  it('attaches the bearer token to the manifest request', () => {
    setTokens({ accessToken: 'jwt-123' });
    const xhr = fakeXhr();

    hlsAuthConfig().xhrSetup(xhr, MANIFEST_ABSOLUTE);

    expect(xhr.setRequestHeader).toHaveBeenCalledWith('Authorization', 'Bearer jwt-123');
  });

  // Regression: S3/MinIO answers 400 "multiple authentication types" when a
  // presigned URL also carries an Authorization header, which broke every
  // playback with hls.js's "Playback failed" banner.
  it('does not send Authorization on presigned segment requests', () => {
    setTokens({ accessToken: 'jwt-123' });
    const xhr = fakeXhr();

    hlsAuthConfig().xhrSetup(xhr, PRESIGNED_SEGMENT);

    expect(xhr.setRequestHeader).not.toHaveBeenCalled();
  });

  it('sends nothing when there is no access token', () => {
    const xhr = fakeXhr();

    hlsAuthConfig().xhrSetup(xhr, MANIFEST_ABSOLUTE);

    expect(xhr.setRequestHeader).not.toHaveBeenCalled();
  });
});
