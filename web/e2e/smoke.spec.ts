import { expect, test, type Route } from '@playwright/test';

const publicSettings = {
  siteName: 'MoYin.CC',
  tagline: '安静的声音栖地',
  registrationEnabled: true,
  passwordMinLength: 3,
  copy: {
    heroKicker: 'AUDIO ISLAND',
    heroTitle: 'MoYin.CC',
    heroSubtitle: '安静的声音栖地',
    primaryCta: '申请访问',
    secondaryCta: '进入账号中心',
    notice: '一个轻量、安静、专注的音频内容入口。',
  },
  links: { libraryUrl: '', supportUrl: '', announcementUrl: '' },
  client: { serverUrl: '', androidDownloadUrl: '', iosGuideText: '', desktopGuideText: '' },
  announcement: { title: '', body: '', linkUrl: '', linkLabel: '', timeline: [] },
  features: { registration: true, showLibraryEntry: false, showSupportEntry: false, showAnnouncements: false },
  operations: { inactivityAutoDisable: false, inactiveDays: 30, newUserGraceDays: 7 },
  sections: { benefits: [], steps: [], faq: [] },
};

test.beforeEach(async ({ page }) => {
  const fulfillApi = (payload: object) => async (route: Route) => {
    const origin = route.request().headers().origin || '*';
    const headers = {
      'access-control-allow-origin': origin,
      'access-control-allow-credentials': 'true',
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
    };
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers });
      return;
    }
    await route.fulfill({ json: payload, headers });
  };

  await page.route('**/api/public/config', fulfillApi(publicSettings));
  await page.route('**/api/public/session-status', fulfillApi({ authenticated: false, admin: false }));
});

test('首页可以访问', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('MoYin.CC');
  await expect(page.getByRole('link', { name: '申请访问' })).toBeVisible();
});

test('登录页可以访问', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: /登录 MoYin\.CC/ })).toBeVisible();
  await expect(page.getByLabel('用户名')).toBeVisible();
});

test('注册页可以访问', async ({ page }) => {
  await page.goto('/register');
  await expect(page.getByRole('heading', { name: '受邀注册' })).toBeVisible();
  await expect(page.getByRole('button', { name: /创建账号/ })).toBeVisible();
});

test('移动端基础页面不会产生横向溢出', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('mobile-'), '仅在移动端项目执行');
  for (const path of ['/', '/login', '/register']) {
    await page.goto(path);
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
  }
});
