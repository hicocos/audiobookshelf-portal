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
  sections: {
    benefits: Array<{ title: string; body: string }>;
    steps: string[];
    faq: Array<{ q: string; a: string }>;
  };
};

export type PortalUser = {
  id: string;
  username: string;
  role: string;
  status: string;
  expiresAt: string | null;
  telegramBound?: boolean;
  telegramUsername?: string | null;
  telegramBoundAt?: string | null;
};

export type TelegramBindTokenResponse = {
  code: string;
  expiresAt: string;
  botUsername: string | null;
  command: string;
};

export type CodeRecord = {
  id: string;
  code: string;
  type: string;
  durationDays: number;
  maxUses: number;
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
  progress: Array<{ id: string; libraryItemId?: string | null; title: string; author?: string; narrator?: string; mediaItemType: string; progressPercent: number; currentHours: number; durationHours: number; isFinished: boolean; lastUpdate?: string | null }>;
  stats: { libraryCount: number; itemPreviewCount: number; progressCount: number };
};

export type AdminLibraryOverview = {
  libraries: LibrarySummary['libraries'];
  users: Array<{
    id: string;
    username: string;
    type: string;
    isActive: boolean;
    lastSeen?: string | null;
    latestListenAt?: string | null;
    progressCount: number;
    portalUserId?: string | null;
    portalStatus?: string | null;
    portalCreatedAt?: string | null;
    inactivityCandidate?: boolean;
    inactivityReason?: string;
  }>;
  stats: { libraryCount: number; upstreamUserCount: number; activeUserCount: number; progressCount: number; portalUserCount?: number; inactiveCandidateCount?: number };
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

export type AdminLibrary = { id: string; name: string; mediaType: string; icon?: string | null; lastScan?: string | null };
export type AdminLibraryItem = { id: string; libraryId?: string | null; title: string; author?: string; narrator?: string; durationHours: number; numTracks: number; addedAt?: string | null };

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

function combineSignals(primary: AbortSignal | null | undefined, timeout: AbortSignal): AbortSignal {
  if (!primary) return timeout;
  return AbortSignal.any([primary, timeout]);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
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
    throw new ApiError(translateError(detail, response.status), { status: response.status, code });
  }
  return data as T;
}

export const api = {
  config: () => request<PublicSettings>('/api/public/config'),
  sessionStatus: () => request<{ authenticated: boolean; admin: boolean; status?: string; role?: string }>('/api/public/session-status'),
  setupStatus: () => request<{ initialized: boolean; setupAvailable: boolean }>('/api/admin/setup-status'),
  register: (username: string, password: string, inviteCode: string) =>
    request<{ user: PortalUser }>('/api/auth/register', {
      method: 'POST', body: JSON.stringify({ username, password, inviteCode }),
    }),
  login: (username: string, password: string) =>
    request<{ user: PortalUser }>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  me: () => request<{ user: PortalUser }>('/api/me'),
  librarySummary: () => request<LibrarySummary>('/api/library/summary'),
  adminLibraryOverview: () => request<AdminLibraryOverview>('/api/library/admin/overview'),
  redeem: (code: string) => request<{ user: PortalUser; redeemedCode: string; upstreamReactivated?: boolean; message?: string }>('/api/me/redeem', {
    method: 'POST', body: JSON.stringify({ code }),
  }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ user: PortalUser }>('/api/me/password', {
      method: 'POST', body: JSON.stringify({ currentPassword, newPassword }),
    }),
  generateTelegramBindToken: () => request<TelegramBindTokenResponse>('/api/me/telegram/bind-token', { method: 'POST' }),
  unbindTelegram: () => request<{ ok: boolean; user: PortalUser }>('/api/me/telegram/binding', { method: 'DELETE' }),
  createCodes: (payload: { type: string; durationDays: number; count: number; maxUses: number; note?: string }) =>
    request<{ codes: CodeRecord[] }>('/api/admin/codes', { method: 'POST', body: JSON.stringify(payload) }),
  listCodes: () => request<{ codes: CodeRecord[] }>('/api/admin/codes'),
  updateCodeStatus: (codeId: string, status: 'active' | 'disabled') =>
    request<{ code: CodeRecord }>(`/api/admin/codes/${codeId}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  deleteCode: (codeId: string) =>
    request<{ ok: boolean; id: string }>(`/api/admin/codes/${codeId}`, { method: 'DELETE' }),
  getPublicSettings: () => request<{ settings: PublicSettings }>('/api/admin/settings/public'),
  updatePublicSettings: (payload: Partial<PublicSettings>) =>
    request<{ settings: PublicSettings }>('/api/admin/settings/public', { method: 'PATCH', body: JSON.stringify(payload) }),
  runInactivityCheck: () =>
    request<{ result: { enabled: boolean; checked: number; disabled: number; candidates?: Array<Record<string, unknown>> }; settings: PublicSettings }>('/api/admin/inactivity/check', { method: 'POST' }),

  // --- Admin user management (replaces direct ABS backend) ---
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
    request<{ summary: { matched: number; affected: number; active: number; expired: number; disabled: number; permanent: number; reactivatable: number; skippedAdmins: number } }>('/api/admin/users/bulk/expiry/preview', { method: 'POST', body: JSON.stringify(payload) }),
  adminBulkExtendUserExpiry: (payload: { extendDays: number; reason?: string }) =>
    request<{ summary: { matched: number; updated: number; reactivated: number; skippedPermanent: number; skippedAdmins: number }; users: AdminUser[] }>('/api/admin/users/bulk/expiry', { method: 'POST', body: JSON.stringify(payload) }),
  adminDeleteUser: (userId: string) =>
    request<{ ok: boolean; id: string }>(`/api/admin/users/${userId}`, { method: 'DELETE' }),

  // --- Admin media library browser (read-only) ---
  adminListLibraries: () => request<{ libraries: AdminLibrary[] }>('/api/library/admin/libraries'),
  adminListLibraryItems: (libraryId: string, limit = 50) =>
    request<{ libraryId: string; items: AdminLibraryItem[]; count: number; limit: number }>(`/api/library/admin/libraries/${libraryId}/items?limit=${limit}`),
};
