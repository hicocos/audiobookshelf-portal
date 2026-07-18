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
  operations: { inactivityAutoDisable: false, inactiveDays: 30, newUserGraceDays: 7, lastInactivityCheckAt: null, lastInactivityDisabled: 0 },
  telegram: {
    renewalEnabled: true, passwordResetEnabled: true, recentListeningEnabled: true, announcementsEnabled: true,
    lifecycleNotificationsEnabled: true, adminEnabled: true, groupMembershipEnabled: false, requiredGroupId: '',
    requiredGroupInviteUrl: '', groupGraceHours: 72, requestsEnabled: true, checkinEnabled: true,
    pointsRedemptionEnabled: true, referralEnabled: true, leaderboardEnabled: true, checkinBasePoints: 10,
    checkinStreakBonusEvery: 7, checkinStreakBonusPoints: 20, pointsPerDay: 100, maxRedeemDays: 30,
    referralRewardPoints: 50, referralInviteValidDays: 7, referralAccountDays: 30, referralMonthlyLimit: 3,
    leaderboardLimit: 10, expiryReminderDays: [7, 3, 1, 0],
  },
  sections: { benefits: [], steps: [], faq: [] },
};

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

test.beforeEach(async ({ page }) => {
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
  await expect(page.getByLabel('确认密码')).toBeVisible();
  await expect(page.getByRole('button', { name: '显示密码' })).toBeVisible();
  await expect(page.getByRole('button', { name: /创建账号/ })).toBeVisible();
});

test('登录页提供清晰的密码恢复入口', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('link', { name: '忘记密码' })).toBeVisible();
});

test('基础页面不会产生横向溢出', async ({ page }) => {
  for (const path of ['/', '/login', '/register']) {
    await page.goto(path);
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
  }
});

test('账号中心使用可展开和收缩的导航抽屉', async ({ context, page }, testInfo) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const capabilities = {
    canListen: true,
    canRenew: true,
    canChangePassword: true,
    canCheckin: true,
    canRedeemPoints: true,
    canRefer: true,
    canRequest: true,
    canViewLeaderboard: true,
    canAdmin: false,
    unavailableReasons: {},
  };
  await page.route('**/api/me{,/**}', fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities }));
  await page.route('http://localhost:8019/api/me{,/**}', fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities }));
  await page.route('**/api/library/summary', fulfillApi({ libraries: [], items: [], progress: [], stats: { libraryCount: 0, itemPreviewCount: 0, progressCount: 0 } }));
  await page.route('**/api/me/rewards', fulfillApi({ balance: 120, lifetimeEarned: 260, leaderboardOptIn: true, streak: 3, lastCheckinDate: '2026-07-17', history: [] }));
  await page.route('**/api/me/referrals', fulfillApi({ items: [] }));
  await page.route('**/api/me/requests', fulfillApi({ items: [] }));
  await page.route('**/api/me/leaderboard', fulfillApi({ entries: [{ rank: 1, displayName: 'a***e', lifetimeEarned: 260 }] }));

  const seenRequests: string[] = [];
  page.on('request', (request) => seenRequests.push(`${request.method()} ${request.url()}`));
  await page.goto('/dashboard');
  await expect.poll(() => seenRequests.filter((value) => value.includes('/api/me'))).not.toEqual([]);
  await expect(page.getByRole('heading', { name: 'alice' })).toBeVisible();
  await expect(page.getByText('账号健康度')).toHaveCount(0);
  await expect(page.getByText('账号正常，可以继续在客户端收听。')).toBeVisible();
  await expect(page.getByLabel('续期码')).toBeVisible();
  const drawer = page.locator('#primary-nav-drawer');
  await expect(drawer).toBeAttached();

  if (testInfo.project.name.startsWith('mobile-')) {
    const trigger = page.getByRole('button', { name: '打开导航菜单' });
    await expect(trigger).toBeVisible();
    await trigger.click();
    await expect(drawer).toHaveClass(/is-open/);
  } else {
    await page.getByRole('button', { name: '收缩导航栏' }).click();
    await expect(drawer).toHaveAttribute('data-collapsed', 'true');
  }

  await page.getByRole('button', { name: /积分权益/ }).click();
  await expect(page.getByRole('heading', { name: '签到、积分与邀请' })).toBeVisible();
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
});

test('账号中心按能力隐藏入口并且不请求禁用功能', async ({ context, page }) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const requested: string[] = [];
  page.on('request', (request) => requested.push(new URL(request.url()).pathname));
  await page.route('**/api/me{,/**}', fulfillApi({
    user: { id: 'u2', username: 'expired-user', role: 'user', status: 'expired', expiresAt: '2026-07-01T00:00:00Z' },
    capabilities: {
      canListen: false,
      canRenew: false,
      canChangePassword: true,
      canCheckin: false,
      canRedeemPoints: false,
      canRefer: false,
      canRequest: false,
      canViewLeaderboard: false,
      canAdmin: false,
      unavailableReasons: { renew: '续期功能当前未开放。' },
    },
  }));
  await page.addInitScript(() => window.sessionStorage.setItem('moyin-dashboard-tab', 'records'));

  await page.goto('/dashboard');
  await expect(page.getByText('续期暂不可用')).toBeVisible();
  await expect(page.getByText('续期功能当前未开放。')).toBeVisible();
  await expect(page.getByRole('button', { name: /收听记录/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /积分权益/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /内容请求/ })).toHaveCount(0);
  await expect(page.getByText('账号中心', { exact: true })).toBeVisible();
  expect(requested).not.toContain('/api/library/summary');
  expect(requested).not.toContain('/api/me/rewards');
  expect(requested).not.toContain('/api/me/referrals');
  expect(requested).not.toContain('/api/me/requests');
  expect(requested).not.toContain('/api/me/leaderboard');
});

test('管理员登录页不预填或暗示固定用户名', async ({ page }) => {
  await page.goto('/admin');
  const username = page.getByLabel('管理员用户名');
  await expect(username).toHaveValue('');
  await expect(username).toHaveAttribute('placeholder', '输入管理员用户名');
  await expect(page.getByText('管理员登录', { exact: true })).toBeVisible();
});

test('管理员账号中心不暴露管理入口或管理员用户名', async ({ context, page }) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  await page.route('**/api/me{,/**}', fulfillApi({
    user: { id: 'admin', username: 'admin', role: 'root', status: 'active', expiresAt: null },
    capabilities: {
      canListen: true,
      canRenew: true,
      canChangePassword: true,
      canCheckin: false,
      canRedeemPoints: false,
      canRefer: false,
      canRequest: false,
      canViewLeaderboard: false,
      canAdmin: true,
      unavailableReasons: {},
    },
  }));
  await page.route('**/api/library/summary', fulfillApi({ libraries: [], items: [], progress: [], stats: { libraryCount: 0, itemPreviewCount: 0, progressCount: 0 } }));

  const seenAdminRequests: string[] = [];
  page.on('request', (request) => seenAdminRequests.push(`${request.method()} ${request.url()}`));
  await page.goto('/dashboard');
  await expect.poll(() => seenAdminRequests.filter((value) => value.includes('/api/me'))).not.toEqual([]);
  await expect(page.getByRole('heading', { name: '账号概览' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'admin' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '管理中心' })).toHaveCount(0);
});
