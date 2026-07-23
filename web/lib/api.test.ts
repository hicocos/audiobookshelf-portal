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

  it('does not add JSON Content-Type to GET requests without a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => '{}' });
    vi.stubGlobal('fetch', fetchMock);

    await api.config();

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.has('Content-Type')).toBe(false);
  });

  it('adds JSON Content-Type when a JSON body is present', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => '{"enabled":true}' });
    vi.stubGlobal('fetch', fetchMock);

    await api.setLeaderboardOptIn(true);

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('sends a Telegram password-reset token only in the request body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true, username: 'alice' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.resetPassword('one-time-token', 'new-password');

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/public/password-reset');
    expect(fetchMock.mock.calls[0][0]).not.toContain('one-time-token');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      token: 'one-time-token',
      newPassword: 'new-password',
    });
  });

  it('validates a password-reset token with POST body instead of a query string', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ valid: true, username: 'alice' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.validatePasswordReset('one-time-token');

    expect(fetchMock.mock.calls[0][0]).toContain('/api/public/password-reset/validate');
    expect(fetchMock.mock.calls[0][0]).not.toContain('one-time-token');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ token: 'one-time-token' });
  });

  it('sends leaderboard consent explicitly', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ enabled: true }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.setLeaderboardOptIn(true);

    expect(fetchMock.mock.calls[0][0]).toContain('/api/me/leaderboard/opt-in');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ enabled: true });
  });

  it('confirms the previewed recipient count when enqueueing a broadcast', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true, batchId: 'batch', queued: 2 }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.adminCreateBroadcast({ audience: 'active', message: '维护通知', confirmCount: 2, idempotencyKey: 'broadcast-123' });

    expect(fetchMock.mock.calls[0][0]).toContain('/api/admin/operations/broadcast');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      audience: 'active',
      message: '维护通知',
      confirmCount: 2,
      idempotencyKey: 'broadcast-123',
    });
  });
});
