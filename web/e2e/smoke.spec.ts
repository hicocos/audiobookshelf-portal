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

const meEndpoint = /\/api\/me(?:\?.*)?$/;

test.beforeEach(async ({ page }) => {
  await page.route('**/api/public/config', fulfillApi(publicSettings));
  await page.route('**/api/public/session-status', fulfillApi({ authenticated: false, admin: false }));
});

test('首页可以访问', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('MoYin.CC');
  await expect(page.getByRole('link', { name: '申请访问' })).toBeVisible();
});

test('首页对待启用会话显示继续绑定而不是重复注册', async ({ page }) => {
  await page.unroute('**/api/public/session-status');
  await page.route('**/api/public/session-status', fulfillApi({ authenticated: true, admin: false, accountStatus: 'pending' }));
  await page.goto('/');
  await expect(page.getByRole('link', { name: '继续绑定 Telegram' })).toHaveAttribute('href', '/dashboard');
  await expect(page.getByRole('link', { name: '申请访问' })).toHaveCount(0);
});

test('390 宽首屏直接呈现待启用账号的关键状态与操作', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.unroute('**/api/public/session-status');
  await page.route('**/api/public/session-status', fulfillApi({ authenticated: true, admin: false, accountStatus: 'pending' }));
  await page.goto('/');
  const continueBinding = page.getByRole('link', { name: '继续绑定 Telegram' });
  await expect(continueBinding).toBeVisible();
  await expect(page.getByText('账号待启用，请完成 Telegram 绑定。')).toBeVisible();
  const box = await continueBinding.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
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

test('密码重置 deep link 从 fragment 读取令牌并立即清除地址栏敏感信息', async ({ page }) => {
  let validatedToken = '';
  await page.route('**/api/public/password-reset/validate', async (route) => {
    validatedToken = JSON.parse(route.request().postData() || '{}').token || '';
    await fulfillApi({ valid: true, username: 'alice', expiresAt: '2026-07-23T12:00:00Z', passwordMinLength: 8 })(route);
  });
  await page.goto('/reset-password#token=deep-link-secret');
  await expect(page.getByText('正在为账号 alice 重置密码。')).toBeVisible();
  expect(validatedToken).toBe('deep-link-secret');
  await expect.poll(() => page.url()).toBe(`${new URL(page.url()).origin}/reset-password`);
});

test('抽屉在 768、1023 使用键盘模态交互，在 1024 恢复桌面导航', async ({ context, page }, testInfo) => {
  test.skip(testInfo.project.name.startsWith('mobile-'), '精确 viewport 仅需在 Chromium 桌面上下文执行');
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const capabilities = { canListen: false, canRenew: false, canChangePassword: true, canCheckin: false, canRedeemPoints: false, canRefer: false, canRequest: false, canViewLeaderboard: false, canAdmin: false, unavailableReasons: {} };
  await page.route(meEndpoint, fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities }));

  for (const width of [768, 1023]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/dashboard');
    const trigger = page.getByRole('button', { name: '打开导航菜单' });
    await expect(trigger).toBeVisible();
    await trigger.focus();
    await page.keyboard.press('Enter');
    const drawer = page.getByRole('dialog', { name: '栏目导航' });
    await expect(drawer).toBeVisible();
    await expect(drawer).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(page.getByRole('button', { name: '关闭导航菜单' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
  }

  await page.setViewportSize({ width: 1024, height: 800 });
  await page.goto('/dashboard');
  await expect(page.getByRole('button', { name: '打开导航菜单' })).toBeHidden();
  await expect(page.getByRole('button', { name: '收缩导航栏' })).toBeVisible();
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
  await page.route(meEndpoint, fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities }));
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
  await page.route(meEndpoint, fulfillApi({
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

test('Dashboard 可对失败模块独立重试而不重新请求账号信息', async ({ context, page }) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const capabilities = { canListen: false, canRenew: false, canChangePassword: true, canCheckin: true, canRedeemPoints: false, canRefer: false, canRequest: false, canViewLeaderboard: false, canAdmin: false, unavailableReasons: {} };
  let meCalls = 0;
  let rewardsCalls = 0;
  let rewardsAvailable = false;
  await page.route(meEndpoint, async (route) => { meCalls += 1; await fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities })(route); });
  await page.route('**/api/me/rewards', async (route) => {
    rewardsCalls += 1;
    if (!rewardsAvailable) await route.fulfill({ status: 503, json: { detail: '暂时不可用' } });
    else await fulfillApi({ balance: 42, lifetimeEarned: 42, leaderboardOptIn: false, streak: 2, lastCheckinDate: null, history: [] })(route);
  });
  await page.goto('/dashboard?tab=rewards');
  await expect(page.getByText(/积分数据暂时无法加载/)).toBeVisible();
  const initialRewardsCalls = rewardsCalls;
  rewardsAvailable = true;
  await page.getByRole('button', { name: '重试积分数据' }).click();
  await expect(page.getByText('当前积分').locator('..')).toContainText('42');
  expect(meCalls).toBe(1);
  expect(rewardsCalls).toBe(initialRewardsCalls + 1);
});

test('Telegram 绑定码显示实时倒计时并轮询完成状态', async ({ context, page }) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const user = { id: 'u1', username: 'alice', role: 'user', status: 'pending', expiresAt: null, telegramBindingRequired: true, telegramBound: false };
  const capabilities = { canListen: false, canRenew: false, canChangePassword: true, canCheckin: false, canRedeemPoints: false, canRefer: false, canRequest: false, canViewLeaderboard: false, canAdmin: false, unavailableReasons: {} };
  await page.route(meEndpoint, fulfillApi({ user, capabilities }));
  await page.route('**/api/me/telegram/bind-token', fulfillApi({ code: 'ABC123', command: '/bind ABC123', botUsername: 'moyin_bot', expiresAt: new Date(Date.now() + 65_000).toISOString() }));
  await page.route('**/api/me/telegram/binding-status', fulfillApi({ bound: true, phase: 'completed', user: { ...user, status: 'active', telegramBound: true, telegramUsername: 'alice_tg' } }));
  await page.goto('/dashboard');
  await page.getByRole('button', { name: '生成绑定码' }).click();
  await expect(page.getByText(/剩余 0[01]:\d{2}/)).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('Telegram 绑定完成');
});

test('签到成功使用弹窗提示', async ({ context, page }, testInfo) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const capabilities = { canListen: false, canRenew: false, canChangePassword: true, canCheckin: true, canRedeemPoints: false, canRefer: false, canRequest: false, canViewLeaderboard: false, canAdmin: false, unavailableReasons: {} };
  await page.route(meEndpoint, fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities }));
  await page.route('**/api/me/rewards', fulfillApi({ balance: 10, lifetimeEarned: 10, leaderboardOptIn: false, streak: 1, lastCheckinDate: '2026-07-23', history: [] }));
  await page.route('**/api/me/checkin', fulfillApi({ alreadyCheckedIn: false, date: '2026-07-23', streak: 1, pointsAwarded: 10, balance: 10 }));
  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: 'alice' })).toBeVisible();
  if (testInfo.project.name.startsWith('mobile-')) await page.getByRole('button', { name: '打开导航菜单' }).click();
  await page.getByRole('button', { name: /积分权益/ }).click();
  await expect(page.getByRole('heading', { name: '签到、积分与邀请' })).toBeVisible();
  await page.getByRole('button', { name: /今日签到/ }).click();
  await expect(page.getByRole('dialog')).toContainText('签到成功');
  await expect(page.getByRole('dialog')).toContainText('获得 10 积分');
});

test('签到成功后积分刷新失败仍显示成功弹窗', async ({ context, page }, testInfo) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const capabilities = { canListen: false, canRenew: false, canChangePassword: true, canCheckin: true, canRedeemPoints: false, canRefer: false, canRequest: false, canViewLeaderboard: false, canAdmin: false, unavailableReasons: {} };
  await page.route(meEndpoint, fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities }));
  let rewardsCalls = 0;
  await page.route('**/api/me/rewards', async (route) => {
    rewardsCalls += 1;
    if (rewardsCalls === 1) await fulfillApi({ balance: 0, lifetimeEarned: 0, leaderboardOptIn: false, streak: 0, lastCheckinDate: null, history: [] })(route);
    else await route.fulfill({ status: 503, json: { detail: 'refresh unavailable' } });
  });
  await page.route('**/api/me/checkin', fulfillApi({ alreadyCheckedIn: false, date: '2026-07-23', streak: 1, pointsAwarded: 10, balance: 10 }));
  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: 'alice' })).toBeVisible();
  if (testInfo.project.name.startsWith('mobile-')) await page.getByRole('button', { name: '打开导航菜单' }).click();
  await page.getByRole('button', { name: /积分权益/ }).click();
  await expect(page.getByRole('heading', { name: '签到、积分与邀请' })).toBeVisible();
  await page.getByRole('button', { name: /今日签到/ }).click();
  await expect(page.getByRole('dialog')).toContainText('签到成功');
  await expect(page.getByText('当前积分').locator('..')).toContainText('10');
});

test('我的请求支持撤销和删除', async ({ context, page }, testInfo) => {
  await context.addCookies([{ name: 'moyin_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  const capabilities = { canListen: false, canRenew: false, canChangePassword: true, canCheckin: false, canRedeemPoints: false, canRefer: false, canRequest: true, canViewLeaderboard: false, canAdmin: false, unavailableReasons: {} };
  await page.route(meEndpoint, fulfillApi({ user: { id: 'u1', username: 'alice', role: 'user', status: 'active', expiresAt: '2027-01-01T00:00:00Z' }, capabilities }));
  const item = { id: 'req-1', title: '斗破苍穹', details: null, status: 'pending', adminNote: null, createdAt: '2026-07-23T00:00:00Z', updatedAt: '2026-07-23T00:00:00Z' };
  await page.route('**/api/me/requests', async (route) => {
    if (route.request().method() === 'GET') await fulfillApi({ items: [item] })(route);
    else await route.fallback();
  });
  await page.route('**/api/me/requests/req-1/cancel', fulfillApi({ item: { ...item, status: 'cancelled' } }));
  await page.route('**/api/me/requests/req-1', fulfillApi({ ok: true, id: 'req-1' }));
  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: 'alice' })).toBeVisible();
  if (testInfo.project.name.startsWith('mobile-')) await page.getByRole('button', { name: '打开导航菜单' }).click();
  await page.getByRole('button', { name: /求有声书/ }).click();
  await expect(page.getByRole('heading', { name: '我的请求' })).toBeVisible();
  await page.getByRole('button', { name: '撤销' }).click();
  await page.getByRole('button', { name: '确认撤销' }).click();
  await expect(page.getByText('已撤销', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '我知道了' }).click();
  await page.getByRole('button', { name: '删除' }).click();
  await page.getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByText('还没有提交内容请求。')).toBeVisible();
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
  await page.route(meEndpoint, fulfillApi({
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
