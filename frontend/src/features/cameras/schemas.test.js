import { describe, expect, it } from 'vitest';
import { cameraFormSchema } from './schemas';

describe('cameraFormSchema', () => {
  const valid = {
    code: 'cam01',
    name: 'Front gate',
    rtsp_url: 'rtsp://mediamtx:8554/cam01',
    site_id: 'rvce-campus',
    enabled: true,
  };

  it('accepts a valid camera', () => {
    expect(cameraFormSchema.safeParse(valid).success).toBe(true);
  });

  it.each([
    ['http://not-rtsp.example/cam01', false],
    ['rtsp://', false],
    ['rtsp://mediamtx:8554/cam01', true],
  ])('rtsp_url %s -> valid=%s', (rtsp_url, expected) => {
    const result = cameraFormSchema.safeParse({ ...valid, rtsp_url });
    expect(result.success).toBe(expected);
  });

  it('rejects a blank required field', () => {
    const result = cameraFormSchema.safeParse({ ...valid, code: '' });
    expect(result.success).toBe(false);
  });

  it('treats location_label as optional', () => {
    const result = cameraFormSchema.safeParse(valid);
    expect(result.success).toBe(true);
  });
});
