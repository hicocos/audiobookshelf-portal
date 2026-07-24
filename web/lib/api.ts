export type PublicSettings = {
  siteName: string;
  tagline: string;
  registrationEnabled: boolean;
  passwordMinLength: number;
  copy: {
    heroKicker: string;
    heroTitle: string;
    heroSubtitle: string;
    primaryCta: string;
    secondaryCta: string;
    notice: string;
  };
  links: {
    libraryUrl: string;
    supportUrl: string;
    announcementUrl: string;
  };
  client: {
    serverUrl: string;
    androidDownloadUrl: string;
    iosGuideText: string;
    desktopGuideText: string;
  };
  announcement: {
    title: string;
    body: string;
    linkUrl: string;
    linkLabel: string;
    timeline?: Array<{ date: string; body: string }>;
  };
  features: {
    registration: boolean;
    showLibraryEntry: boolean;
    showSupportEntry: boolean;
    showAnnouncements: boolean;
  };
  operations: {
    inactivityAutoDisable: boolean;
    inactiveDays: number;
    newUserGraceDays: number;
    lastInactivityCheckAt?: string | null;
    lastInactivityDisabled?: number;
  };
  telegram: {
    renewalEnabled: boolean;
    passwordResetEnabled: boolean;
    recentListeningEnabled: boolean;
    announcementsEnabled: boolean;
    lifecycleNotificationsEnabled: boolean;
    adminEnabled: boolean;
    groupMembershipEnabled: boolean;
    requiredGroupId: string;
    requiredGroupInviteUrl: string;
    groupGraceHours: number;
    botUsername?: string | null;
    requestsEnabled: boolean;
    checkinEnabled: boolean;
    pointsRedemptionEnabled: boolean;
    referralEnabled: boolean;
    leaderboardEnabled: boolean;
    checkinBasePoints: number;
    checkinStreakBonusEvery: number;
    checkinStreakBonusPoints: number;
    pointsPerDay: number;
    maxRedeemDays: number;
    referralRewardPoints: number;
    referralInviteValidDays: number;
    referralAccountDays: number;
    referralMonthlyLimit: number;
    leaderboardLimit: number;
    expiryReminderDays: number[];
  };
  sections: {
    benefits: Array<{ title: string; body: string }>;
    steps: string[];
    faq: Array<{ q: string; a: string }>;
  };
};

export const DEFAULT_TELEGRAM_SETTINGS: PublicSettings['telegram'] = {
  renewalEnabled: true,
  passwordResetEnabled: true,
  recentListeningEnabled: true,
  announcementsEnabled: true,
  lifecycleNotificationsEnabled: true,
  adminEnabled: true,
  groupMembershipEnabled: false,
  requiredGroupId: '',
  requiredGroupInviteUrl: '',
  groupGraceHours: 72,
  requestsEnabled: true,
  checkinEnabled: true,
  pointsRedemptionEnabled: true,
  referralEnabled: true,
  leaderboardEnabled: false,
  checkinBasePoints: 10,
  checkinStreakBonusEvery: 7,
  checkinStreakBonusPoints: 20,
  pointsPerDay: 100,
  maxRedeemDays: 30,
  referralRewardPoints: 50,
  referralInviteValidDays: 7,
  referralAccountDays: 30,
  referralMonthlyLimit: 3,
  leaderboardLimit: 10,
  expiryReminderDays: [7, 3, 1, 0],
};

export type PortalUser = {
  id: string;
  username: string;
  role: string;
  status: string;
  expiresAt: string | null;
  telegramBound?: boolean;
  telegramBindingRequired?: boolean;
  telegramUsername?: string | null;
  telegramBoundAt?: string | null;
};

export type UserCapabilities = {
  canListen: boolean;
  canRenew: boolean;
  canChangePassword: boolean;
  canCheckin: boolean;
  canRedeemPoints: boolean;
  canRefer: boolean;
  canRequest: boolean;
  canViewLeaderboard: boolean;
  canAdmin: boolean;
  unavailableReasons: Record<string, string>;
};

export type TelegramBindTokenResponse = {
  code: string;
  expiresAt: string;
  botUsername: string | null;
  command: string;
  bindingSessionId?: string;
  attemptsRemaining?: number;
  phase?: string;
};

export type CodeRecord = {
  id: string;
  code: string;
  type: string;
  durationDays: number;
  maxUses: number;
  perUserMaxUses: number;
  usedCount: number;
  status: string;
  expiresAt: string | null;
  designatedUsername: string | null;
  note: string | null;
  createdAt: string | null;
};

export type LibrarySummary = {
  libraries: Array<{ id: string; name: string; mediaType: string; icon?: string | null; lastScan?: string | null }>;
  items: Array<{ id: string; libraryId?: string | null; title: string; author?: string; narrator?: string; durationHours: number; numTracks: number; addedAt?: string | null }>;
  progress: Array<{ id: string; libraryItemId?: string | null; openUrl?: string | null; title: string; author?: string; narrator?: string; mediaItemType: string; progressPercent: number; currentHours: number; durationHours: number; isFinished: boolean; lastUpdate?: string | null }>;
  stats: { libraryCount: number; itemPreviewCount: number; progressCount: number };
};

export type AdminUser = {
  id: string;
  username: string;
  email: string | null;
  role: string;
  status: string;
  absUserId: string | null;
  absUsername: string | null;
  expiresAt: string | null;
  isExpired: boolean;
  createdAt: string | null;
  lastLoginAt: string | null;
  upstreamActive: boolean | null;
  upstreamFound: boolean;
};

export type AdminUserList = {
  users: AdminUser[];
  stats: { total: number; active: number; disabled: number; expired: number };
  upstreamAvailable: boolean;
};

export type RewardSummary = {
  balance: number;
  lifetimeEarned: number;
  leaderboardOptIn: boolean;
  streak: number;
  lastCheckinDate: string | null;
  history: Array<{ amount: number; balanceAfter: number; kind: string; createdAt: string }>;
};

export type LeaderboardEntry = {
  rank: number;
  displayName: string;
  lifetimeEarned: number;
};

export type ReferralRecord = {
  id: string;
  code: string | null;
  expiresAt: string;
  rewardPoints: number;
  status?: 'available' | 'used' | 'expired' | 'disabled';
  used: boolean;
  settledAt: string | null;
  createdAt: string;
};

export type MediaRequestRecord = {
  id: string;
  username?: string;
  title: string;
  details: string | null;
  status: string;
  adminNote: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AdminOperationsOverview = {
  users: { active: number; expired: number; disabled: number };
  pendingRequests: number;
  notifications: { pending: number; retry: number; sending: number; failed: number };
  groupGrace: number;
  referrals: number;
  pointAccounts: number;
  worker: { healthy: boolean; reason?: string; lagSeconds?: number; lastError?: string | null };
};

export type AdminNotification = {
  id: string;
  telegramId: string;
  kind: string;
  message: string;
  status: string;
  attempts: number;
  version: number;
  claimedAt: string | null;
  lastError: string | null;
  createdAt: string;
  sentAt: string | null;
};

export type AdminMembership = {
  id: string;
  username: string;
  telegramId: string;
  groupId: string;
  status: string;
  graceExpiresAt: string | null;
  lastCheckedAt: string;
};

export type AuditEntry = {
  id: string;
  actor: string | null;
  action: string;
  targetType: string | null;
  targetId: string | null;
  detail: string | null;
  createdAt: string;
};

export type BroadcastAudience = 'active' | 'expiring_7d' | 'expired' | 'all_bound';

export type BroadcastPreview = {
  audience: BroadcastAudience;
  count: number;
  sample: string[];
};

export type AdminLibraryOverview = {
  libraries: LibrarySummary['libraries'];
  users: Array<{
    id: string;
    username: string;
    type: string;
    isActive: boolean;
    latestListenAt?: string | null;
    progressCount: number;
    portalStatus?: string | null;
    inactivityCandidate?: boolean;
    inactivityReason?: string;
  }>;
  stats: {
    libraryCount: number;
    upstreamUserCount: number;
    activeUserCount: number;
    progressCount: number;
    portalUserCount: number;
    inactiveCandidateCount: number;
  };
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8019';

function translateError(detail: unknown, status: number): string {
  if (Array.isArray(detail)) {
    const fields = detail.map(item => {
      if (item && typeof item === 'object' && 'loc' in item) {
        const loc = (item as { loc?: unknown }).loc;
        if (Array.isArray(loc)) return String(loc[loc.length - 1] || '');
      }
      return '';
    });
    if (fields.includes('username')) return '用户名格式不正确：只能使用英文、数字、下划线、点或短横线。';
    if (fields.includes('password')) return '密码格式不正确，请检查长度。';
    if (fields.includes('inviteCode') || fields.includes('code')) return '卡密格式不正确，请检查后重试。';
    return '提交内容格式不正确，请检查后重试。';
  }

  const text = String(detail || '').trim();
  const dictionary: Record<string, string> = {
    'Username already exists': '用户名已存在，请换一个用户名。',
    'code not found': '卡密不存在，请检查后重试。',
    'code is not active': '卡密未启用，请联系管理员。',
    'code expired': '卡密已过期，请联系管理员重新获取。',
    'code already used': '卡密已被使用，请联系管理员重新获取。',
    'code designated for another username': '这张卡密已指定给其他账号使用。',
    'code is not an invite code': '这是续期码，不能用于注册。注册请使用邀请码。',
    'code is not a renewal code': '这是注册邀请码，不能用于续期。续期请使用续期码。',
    'account already permanent': '你的账号已是永久有效，无需再使用永久续期码。',
    'Unsupported code type': '卡密类型不支持，请联系管理员。',
    'Invalid username or password': '用户名或密码错误。',
    'Invalid session': '登录状态无效，请重新登录。',
    'User not found': '账号不存在，请重新登录或联系管理员。',
    'Upstream media server user creation failed. Please contact the administrator.': '创建媒体账号失败，请联系管理员检查服务配置。',
    '该用户名已存在。': '该用户名已存在。',
    '未找到该用户。': '未找到该用户。',
    '媒体服务器暂时不可用，操作未完成，请稍后重试。': '媒体服务器暂时不可用，操作未完成，请稍后重试。',
    '媒体库数据暂时不可用，请稍后重试。': '媒体库数据暂时不可用，请稍后重试。',
    '请提供 expiresAt、extendDays 或 clear 之一。': '请选择一种有效期操作方式。',
    'Code not found': '卡密不存在，请刷新后重试。',
    'Code has no remaining uses': '这张卡密已经没有剩余次数。',
    '当前密码不正确。': '当前密码不正确。',
    '新密码不能与当前密码相同。': '新密码不能与当前密码相同。',
    '媒体服务器暂时不可用，密码未修改，请稍后重试。': '媒体服务器暂时不可用，密码未修改，请稍后重试。',
    'invalid or expired password reset token': '重置链接无效或已过期，请回到 Telegram Bot 重新生成。',
    'invalid password reset token': '重置链接无效，请回到 Telegram Bot 重新生成。',
    'account is not eligible for password reset': '当前账号状态不能重置密码，请联系管理员。',
    'media server unavailable; password not changed': '媒体服务器暂时不可用，密码未修改，请稍后重试。',
  };
  if (dictionary[text]) return dictionary[text];
  if (text.startsWith('Password must be at least')) {
    const match = text.match(/at least (\d+) characters/);
    return `密码至少需要 ${match?.[1] || ''} 位。`.trim();
  }
  if (text.startsWith('Internal Server Error')) return '服务器内部错误，请联系管理员。';
  if (status === 401) return '登录已失效，请重新登录。';
  if (status === 403) {
    if (text === 'Account is not active') return '账号已停用或不可登录，请联系管理员处理。';
    return '没有权限执行此操作。';
  }
  if (status === 404) return '请求的内容不存在。';
  if (status === 429) return '操作过于频繁，请稍后再试。';
  if (status >= 500) return '服务器暂时不可用，请稍后重试或联系管理员。';
  return text || `请求失败（HTTP ${status}）`;
}

export async function clearSession() {
  await request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' });
}

export class ApiError extends Error {
  status: number;
  code?: string;
  cause?: unknown;

  constructor(message: string, options: { status: number; code?: string; cause?: unknown }) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    this.cause = options.cause;
  }
}

const DEFAULT_TIMEOUT_MS = 12_000;
let sessionExpiredDispatched = false;

function notifySessionExpired(path: string) {
  if (sessionExpiredDispatched || !path.startsWith('/api/me')) return;
  sessionExpiredDispatched = true;
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('moyin:session-expired'));
}

function combineSignals(primary: AbortSignal | null | undefined, timeout: AbortSignal): AbortSignal {
  if (!primary) return timeout;
  return AbortSignal.any([primary, timeout]);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  let response: Response;
  try {
    const timeout = AbortSignal.timeout(DEFAULT_TIMEOUT_MS);
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      signal: combineSignals(options.signal, timeout),
      cache: 'no-store',
      credentials: 'include',
    });
  } catch (cause) {
    if (cause instanceof Error && (cause.name === 'AbortError' || cause.name === 'TimeoutError')) {
      throw new ApiError('请求超时，请检查网络后重试。', { status: 0, code: 'timeout', cause });
    }
    throw new ApiError('网络连接失败，请检查网络后重试。', { status: 0, code: 'network_error', cause });
  }
  const text = await response.text();
  let data: Record<string, unknown> = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text || `HTTP ${response.status}` };
  }
  if (!response.ok) {
    const detail = data.detail || data.message || `HTTP ${response.status}`;
    const code = typeof data.code === 'string' ? data.code : undefined;
    if (response.status === 401) notifySessionExpired(path);
    throw new ApiError(translateError(detail, response.status), { status: response.status, code });
  }
  return data as T;
}

export const api = {
  config: () => request<PublicSettings>('/api/public/config'),
  sessionStatus: () => request<{ authenticated: boolean; admin: boolean; accountStatus?: string; status?: string; role?: string }>('/api/public/session-status'),
  validatePasswordReset: (token: string) =>
    request<{ valid: boolean; username: string; expiresAt: string; passwordMinLength: number }>('/api/public/password-reset/validate', {
      method: 'POST', body: JSON.stringify({ token }),
    }),
  resetPassword: (token: string, newPassword: string) =>
    request<{ ok: boolean; username: string }>('/api/public/password-reset', {
      method: 'POST', body: JSON.stringify({ token, newPassword }),
    }),
  setupStatus: () => request<{ initialized: boolean; setupAvailable: boolean }>('/api/admin/setup-status'),
  register: (username: string, password: string, inviteCode: string) =>
    request<{ user: PortalUser }>('/api/auth/register', {
      method: 'POST', body: JSON.stringify({ username, password, inviteCode }),
    }),
  login: (username: string, password: string) =>
    request<{ user: PortalUser }>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  me: () => request<{ user: PortalUser; capabilities: UserCapabilities; community?: { membership: string; graceDeadline: string | null; policyScope: string; recoveryAction: string | null }; upstream?: { state: string; lastSuccessfulSyncAt: string | null } }>('/api/me'),
  exportMyData: () => request<Record<string, unknown>>('/api/me/export'),
  librarySummary: () => request<LibrarySummary>('/api/library/summary'),
  redeem: (code: string) => request<{ user: PortalUser; redeemedCode: string; upstreamReactivated?: boolean; message?: string }>('/api/me/redeem', {
    method: 'POST', body: JSON.stringify({ code }),
  }),
  renewalPreview: (code: string) => request<{ durationDays: number; currentExpiresAt: string | null; nextExpiresAt: string | null; previewToken: string; operationId: string; previewExpiresAt: string }>('/api/me/renewal-preview', { method: 'POST', body: JSON.stringify({ code }) }),
  renewalConfirm: (previewToken: string, operationId: string) => request<{ user: PortalUser; redeemedCode: string; upstreamReactivated?: boolean; message?: string }>('/api/me/renewal-confirm', { method: 'POST', body: JSON.stringify({ previewToken, operationId }) }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ user: PortalUser }>('/api/me/password', {
      method: 'POST', body: JSON.stringify({ currentPassword, newPassword }),
    }),
  generateTelegramBindToken: () => request<TelegramBindTokenResponse>('/api/me/telegram/bind-token', { method: 'POST' }),
  telegramBindingStatus: () => request<{ bound: boolean; phase: string; expiresAt?: string; attemptsRemaining?: number; user?: PortalUser; operation?: { completed: boolean; retryRequired: boolean; errorCategory?: string | null } | null }>('/api/me/telegram/binding-status'),
  unbindTelegram: () => request<{ ok: boolean; user: PortalUser }>('/api/me/telegram/binding', { method: 'DELETE' }),
  rewards: () => request<RewardSummary>('/api/me/rewards'),
  checkin: () => request<{ alreadyCheckedIn: boolean; date: string; streak: number; pointsAwarded: number; balance: number }>('/api/me/checkin', { method: 'POST' }),
  redeemPoints: (days: number, idempotencyKey: string) => request<{ days: number; cost: number; balance: number; expiresAt: string; upstreamReactivated: boolean; idempotentReplay: boolean }>('/api/me/points/redeem', { method: 'POST', body: JSON.stringify({ days, idempotencyKey }) }),
  leaderboard: () => request<{ entries: LeaderboardEntry[] }>('/api/me/leaderboard'),
  setLeaderboardOptIn: (enabled: boolean) => request<{ enabled: boolean }>('/api/me/leaderboard/opt-in', { method: 'POST', body: JSON.stringify({ enabled }) }),
  referrals: () => request<{ items: ReferralRecord[] }>('/api/me/referrals'),
  createReferral: () => request<{ code: string; expiresAt: string; accountDays: number; rewardPoints: number; existing: boolean }>('/api/me/referrals', { method: 'POST' }),
  mediaRequests: () => request<{ items: MediaRequestRecord[] }>('/api/me/requests'),
  createMediaRequest: (payload: { title: string; details?: string; confirmDifferentVersion?: boolean }) => request<{ item: MediaRequestRecord }>('/api/me/requests', { method: 'POST', body: JSON.stringify(payload) }),
  cancelMediaRequest: (requestId: string) => request<{ item: MediaRequestRecord }>(`/api/me/requests/${requestId}/cancel`, { method: 'POST' }),
  deleteMediaRequest: (requestId: string) => request<{ ok: boolean; id: string }>(`/api/me/requests/${requestId}`, { method: 'DELETE' }),
  createCodes: (payload: { type: string; durationDays: number; count: number; maxUses: number; perUserMaxUses: number; expiresAt?: string; designatedUsername?: string; note?: string }) =>
    request<{ codes: CodeRecord[] }>('/api/admin/codes', { method: 'POST', body: JSON.stringify(payload) }),
  listCodes: () => request<{ codes: CodeRecord[] }>('/api/admin/codes'),
  updateCodeStatus: (codeId: string, status: 'active' | 'disabled') =>
    request<{ code: CodeRecord }>(`/api/admin/codes/${codeId}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  deleteCode: (codeId: string) =>
    request<{ ok: boolean; id: string }>(`/api/admin/codes/${codeId}`, { method: 'DELETE' }),
  getPublicSettings: () => request<{ settings: PublicSettings; revision: string }>('/api/admin/settings/public'),
  updatePublicSettings: (payload: Partial<PublicSettings>, revision?: string) =>
    request<{ settings: PublicSettings; revision: string }>('/api/admin/settings/public', {
      method: 'PATCH',
      headers: revision ? { 'If-Match': revision } : undefined,
      body: JSON.stringify(payload),
    }),
  adminListUsers: () => request<AdminUserList>('/api/admin/users'),
  adminCreateUser: (payload: { username: string; password: string; durationDays: number; email?: string; note?: string }) =>
    request<{ user: AdminUser }>('/api/admin/users', { method: 'POST', body: JSON.stringify(payload) }),
  adminSetUserPassword: (userId: string, password: string) =>
    request<{ user: AdminUser }>(`/api/admin/users/${userId}/password`, { method: 'POST', body: JSON.stringify({ password }) }),
  adminSetUserStatus: (userId: string, action: 'enable' | 'disable') =>
    request<{ user: AdminUser }>(`/api/admin/users/${userId}/status`, { method: 'POST', body: JSON.stringify({ action }) }),
  adminSetUserExpiry: (userId: string, payload: { expiresAt?: string; extendDays?: number; clear?: boolean }) =>
    request<{ user: AdminUser }>(`/api/admin/users/${userId}/expiry`, { method: 'POST', body: JSON.stringify(payload) }),
  adminBulkExtendUserExpiryPreview: (payload: { extendDays: number }) =>
    request<{ summary: { matched: number; affected: number; active: number; expired: number; disabled: number; permanent: number; reactivatable: number; skippedAdmins: number }; previewToken: string; operationId: string; expiresAt: string }>('/api/admin/users/bulk/expiry/preview', { method: 'POST', body: JSON.stringify(payload) }),
  adminBulkExtendUserExpiry: (payload: { extendDays: number; reason?: string; previewToken: string; operationId: string }) =>
    request<{ summary: { matched: number; updated: number; reactivated: number; skippedPermanent: number; skippedAdmins: number }; users: AdminUser[] }>('/api/admin/users/bulk/expiry', { method: 'POST', body: JSON.stringify(payload) }),
  adminDeleteUser: (userId: string) =>
    request<{ ok: boolean; id: string }>(`/api/admin/users/${userId}`, { method: 'DELETE' }),
  adminOperationsOverview: () => request<AdminOperationsOverview>('/api/admin/operations/overview'),
  adminRequests: (status?: string) => request<{ items: MediaRequestRecord[] }>(`/api/admin/operations/requests${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  adminUpdateRequest: (requestId: string, status: 'accepted' | 'available' | 'rejected', note?: string) => request<{ item: MediaRequestRecord }>(`/api/admin/operations/requests/${requestId}`, { method: 'POST', body: JSON.stringify({ status, note }) }),
  adminNotifications: (status?: string) => request<{ items: AdminNotification[] }>(`/api/admin/operations/notifications${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  adminRetryNotification: (notificationId: string, expectedVersion: number) => request<{ ok: boolean; status: string; version: number }>(`/api/admin/operations/notifications/${notificationId}/retry`, { method: 'POST', body: JSON.stringify({ expectedVersion }) }),
  adminPreviewBroadcast: (audience: BroadcastAudience) => request<BroadcastPreview>(`/api/admin/operations/broadcast/preview?audience=${encodeURIComponent(audience)}`),
  adminCreateBroadcast: (payload: { audience: BroadcastAudience; message: string; confirmCount: number; idempotencyKey: string }) => request<{ ok: boolean; batchId: string; queued: number; idempotentReplay: boolean }>('/api/admin/operations/broadcast', { method: 'POST', body: JSON.stringify(payload) }),
  adminMemberships: (status?: string) => request<{ items: AdminMembership[] }>(`/api/admin/operations/memberships${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  adminAudit: (limit = 100) => request<{ items: AuditEntry[] }>(`/api/admin/operations/audit?limit=${limit}`),
  adminAdjustPoints: (payload: { userId: string; amount: number; note: string }) => request<{ ok: boolean; balance: number }>('/api/admin/operations/points/adjust', { method: 'POST', body: JSON.stringify(payload) }),
  adminPreviewInactivity: () => request<{ checked: number; candidates: Array<{ portalUserId: string; username: string; shouldDisable: boolean; reason: string; latestListenAt: string | null }> }>('/api/admin/operations/inactivity/preview', { method: 'POST' }),
  adminLibraryOverview: () => request<AdminLibraryOverview>('/api/library/admin/overview'),
};
