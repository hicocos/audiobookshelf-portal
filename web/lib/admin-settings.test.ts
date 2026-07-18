import { describe, expect, it } from 'vitest';
import { DEFAULT_ADMIN_SETTINGS, hydrateAdminSettings } from '@/lib/admin-settings';

describe('hydrateAdminSettings', () => {
  it('deeply fills missing settings and prepares editable text fields', () => {
    const input = {
      siteName: '测试站点',
      passwordMinLength: 9,
      copy: { heroTitle: '新的标题' },
      telegram: { renewalEnabled: false, expiryReminderDays: [3, 1] },
      announcement: {
        timeline: [
          { date: '2026-07-17', body: '上线' },
          { date: '', body: '持续维护' },
        ],
      },
      sections: {
        steps: ['领取邀请码', '登录'],
        faq: [{ q: '如何加入？', a: '请联系管理员。' }],
      },
    };

    const result = hydrateAdminSettings(input);

    expect(result.settings.siteName).toBe('测试站点');
    expect(result.settings.passwordMinLength).toBe(9);
    expect(result.settings.copy.heroTitle).toBe('新的标题');
    expect(result.settings.copy.primaryCta).toBe(DEFAULT_ADMIN_SETTINGS.copy.primaryCta);
    expect(result.settings.client).toEqual(DEFAULT_ADMIN_SETTINGS.client);
    expect(result.settings.telegram.renewalEnabled).toBe(false);
    expect(result.settings.telegram.expiryReminderDays).toEqual([3, 1]);
    expect(result.settings.telegram.passwordResetEnabled).toBe(true);
    expect(result.stepsText).toBe('领取邀请码\n登录');
    expect(result.faqText).toBe('如何加入？|请联系管理员。');
    expect(result.timelineText).toBe('2026-07-17|上线\n|持续维护');
  });

  it('returns fresh nested values without mutating the defaults', () => {
    const result = hydrateAdminSettings({});

    result.settings.copy.heroTitle = '已修改';
    result.settings.sections.steps.push('临时步骤');

    expect(DEFAULT_ADMIN_SETTINGS.copy.heroTitle).not.toBe('已修改');
    expect(DEFAULT_ADMIN_SETTINGS.sections.steps).toEqual([]);
  });
});
