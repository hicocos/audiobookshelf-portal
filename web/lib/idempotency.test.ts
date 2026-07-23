import { describe, expect, it } from 'vitest';
import { idempotencyAttempt } from './idempotency';

describe('idempotencyAttempt', () => {
  it('reuses the key while retrying the same intent', () => {
    const first = idempotencyAttempt(null, 'redeem:3', () => 'key-1');
    const retry = idempotencyAttempt(first, 'redeem:3', () => 'key-2');
    expect(retry).toEqual({ signature: 'redeem:3', key: 'key-1' });
  });

  it('creates a new key when the intent changes', () => {
    const first = { signature: 'redeem:3', key: 'key-1' };
    expect(idempotencyAttempt(first, 'redeem:5', () => 'key-2')).toEqual({ signature: 'redeem:5', key: 'key-2' });
  });
});
