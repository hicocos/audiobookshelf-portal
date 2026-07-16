import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '@/lib/api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ApiError', () => {
  it('preserves status, error code, and cause for callers', () => {
    const cause = new TypeError('connection refused');
    const error = new ApiError('网络连接失败', {
      status: 0,
      code: 'network_error',
      cause,
    });

    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe('ApiError');
    expect(error.message).toBe('网络连接失败');
    expect(error.status).toBe(0);
    expect(error.code).toBe('network_error');
    expect(error.cause).toBe(cause);
  });

  it('normalizes fetch failures into a network ApiError', async () => {
    const cause = new TypeError('fetch failed');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(cause));

    await expect(api.config()).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
      code: 'network_error',
      cause,
    });
  });

  it('keeps the HTTP status while translating an API error response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Invalid session', code: 'invalid_session' }),
    }));

    await expect(api.config()).rejects.toMatchObject({
      name: 'ApiError',
      message: '登录状态无效，请重新登录。',
      status: 401,
      code: 'invalid_session',
    });
  });
});
