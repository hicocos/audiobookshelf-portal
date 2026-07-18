import { describe, expect, it } from 'vitest';
import { formatShanghaiDateTime, SITE_TIME_ZONE } from '@/lib/datetime';

describe('Shanghai date formatting', () => {
  it('always formats UTC input as China Standard Time', () => {
    expect(SITE_TIME_ZONE).toBe('Asia/Shanghai');
    expect(formatShanghaiDateTime('2026-07-17T00:00:00Z')).toBe(
      '2026-07-17 08:00:00',
    );
  });

  it('returns the requested fallback for invalid values', () => {
    expect(formatShanghaiDateTime('not-a-date', '无记录')).toBe('无记录');
  });
});
