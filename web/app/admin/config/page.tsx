'use client';

import {
  Activity,
  Bell,
  BookOpen,
  CalendarClock,
  ClipboardList,
  Copy,
  ExternalLink,
  KeyRound,
  LogOut,
  Power,
  RefreshCcw,
  Save,
  Search,
  Settings2,
  Trash2,
  UserPlus,
  Users,
} from 'lucide-react';
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { AccessibleModal } from '@/components/accessible-modal';
import { NavDrawer } from '@/components/nav-drawer';
import {
  Button,
  LoadingScreen,
  Panel,
  SectionHeader,
  Sheet,
  ShellBackdrop,
  StatusNote,
  WordMark,
} from '@/components/ui';
import {
  AdminLibraryOverview, AdminMembership, AdminNotification, AdminOperationsOverview, AdminUser, api, ApiError, AuditEntry,
  BroadcastAudience, BroadcastPreview, clearSession, CodeRecord, MediaRequestRecord, PublicSettings,
} from '@/lib/api';
import { DEFAULT_ADMIN_SETTINGS, hydrateAdminSettings } from '@/lib/admin-settings';
import { formatShanghaiDateTime } from '@/lib/datetime';
import { idempotencyAttempt, IdempotencyAttempt } from '@/lib/idempotency';

const requestStatusText: Record<string, string> = { pending: '待处理', accepted: '已受理', available: '已上架', rejected: '未采纳' };
const membershipStatusText: Record<string, string> = { member: '群组成员', grace: '宽限期', disabled: '已停用' };
type AdminTab = 'overview' | 'accounts' | 'codes' | 'operations' | 'library' | 'settings';
type ActionField = {
  name: string;
  label: string;
  type?: 'text' | 'password' | 'number' | 'textarea';
  initial?: string;
  required?: boolean;
  min?: number;
  max?: number;
};
type ActionDialogConfig = {
  title: string;
  body: string;
  confirmText: string;
  danger?: boolean;
  fields?: ActionField[];
  onSubmit: (values: Record<string, string>) => void | Promise<void>;
};

export default function AdminConfigPage() {
  const [tab, setTab] = useState<AdminTab>('overview');
  const [settings, setSettings] = useState<PublicSettings>(DEFAULT_ADMIN_SETTINGS);
  const [stepsText, setStepsText] = useState('');
  const [faqText, setFaqText] = useState('');
  const [timelineText, setTimelineText] = useState('');
  const [expiryReminderDaysText, setExpiryReminderDaysText] = useState('7,3,1,0');
  const [message, setMessage] = useState('正在验证管理员登录状态…');
  const [ready, setReady] = useState(false);
  const [settingsRevision, setSettingsRevision] = useState('');
  const [busy, setBusy] = useState('');
  const [accounts, setAccounts] = useState<AdminUser[]>([]);
  const [accountStats, setAccountStats] = useState({ total: 0, active: 0, disabled: 0, expired: 0 });
  const [upstreamAvailable, setUpstreamAvailable] = useState(true);
  const [accountQuery, setAccountQuery] = useState('');
  const [newUser, setNewUser] = useState({ username: '', password: '', durationDays: 30 });
  const [codes, setCodes] = useState<CodeRecord[]>([]);
  const [codeForm, setCodeForm] = useState({ type: 'register', durationDays: 30, count: 5, maxUses: 1, perUserMaxUses: 1, expiresAt: '', designatedUsername: '', note: '' });
  const [bulkDays, setBulkDays] = useState(7);
  const [bulkReason, setBulkReason] = useState('服务器波动补偿');
  const [bulkPreview, setBulkPreview] = useState<Awaited<ReturnType<typeof api.adminBulkExtendUserExpiryPreview>> | null>(null);
  const [operationsOverview, setOperationsOverview] = useState<AdminOperationsOverview | null>(null);
  const [requests, setRequests] = useState<MediaRequestRecord[]>([]);
  const [notifications, setNotifications] = useState<AdminNotification[]>([]);
  const [memberships, setMemberships] = useState<AdminMembership[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [library, setLibrary] = useState<AdminLibraryOverview | null>(null);
  const [inactivityPreview, setInactivityPreview] = useState<Awaited<ReturnType<typeof api.adminPreviewInactivity>> | null>(null);
  const [requestFilter, setRequestFilter] = useState('open');
  const [notificationFilter, setNotificationFilter] = useState('problem');
  const [broadcastAudience, setBroadcastAudience] = useState<BroadcastAudience>('active');
  const [broadcastMessage, setBroadcastMessage] = useState('');
  const [broadcastPreview, setBroadcastPreview] = useState<BroadcastPreview | null>(null);
  const broadcastAttemptRef = useRef<IdempotencyAttempt | null>(null);
  const broadcastInFlightRef = useRef(false);
  const [actionDialog, setActionDialog] = useState<ActionDialogConfig | null>(null);

  function hydrate(value: Partial<PublicSettings>) {
    const result = hydrateAdminSettings(value);
    setSettings(result.settings);
    setStepsText(result.stepsText);
    setFaqText(result.faqText);
    setTimelineText(result.timelineText);
    setExpiryReminderDaysText(result.settings.telegram.expiryReminderDays.join(','));
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const session = await api.sessionStatus().catch(() => ({ authenticated: false, admin: false }));
      if (cancelled) return;
      if (!session.authenticated || !session.admin) {
        setMessage('请先登录管理员账号，正在跳转登录页…');
        window.setTimeout(() => { location.href = '/admin'; }, 700);
        return;
      }
      const results = await Promise.allSettled([
        api.getPublicSettings(),
        api.adminListUsers(),
        api.listCodes(),
        api.adminOperationsOverview(),
        api.adminRequests(),
        api.adminNotifications(),
        api.adminMemberships(),
        api.adminAudit(50),
        api.adminLibraryOverview(),
      ]);
      if (cancelled) return;
      const [settingsResult, accountsResult, codesResult] = results;
      if (settingsResult.status === 'fulfilled') {
        hydrate(settingsResult.value.settings);
        setSettingsRevision(settingsResult.value.revision);
        setReady(true);
      } else {
        setMessage('配置加载失败，请刷新后重试。');
        return;
      }
      if (accountsResult.status === 'fulfilled') {
        setAccounts(accountsResult.value.users);
        setAccountStats(accountsResult.value.stats);
        setUpstreamAvailable(accountsResult.value.upstreamAvailable);
      }
      if (codesResult.status === 'fulfilled') setCodes(codesResult.value.codes);
      if (results[3].status === 'fulfilled') setOperationsOverview(results[3].value);
      if (results[4].status === 'fulfilled') setRequests(results[4].value.items);
      if (results[5].status === 'fulfilled') setNotifications(results[5].value.items);
      if (results[6].status === 'fulfilled') setMemberships(results[6].value.items);
      if (results[7].status === 'fulfilled') setAudit(results[7].value.items);
      if (results[8].status === 'fulfilled') setLibrary(results[8].value);
      const failed = results.filter((item) => item.status === 'rejected').length;
      setMessage(failed ? `管理台已打开，但有 ${failed} 个模块加载失败。` : '');
    }
    void load();
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    const saved = window.sessionStorage.getItem('moyin-admin-tab');
    if (saved && ['overview', 'accounts', 'codes', 'operations', 'library', 'settings'].includes(saved)) setTab(saved as AdminTab);
  }, []);
  useEffect(() => { window.sessionStorage.setItem('moyin-admin-tab', tab); }, [tab]);

  const filteredAccounts = useMemo(() => {
    const query = accountQuery.trim().toLowerCase();
    if (!query) return accounts;
    return accounts.filter((user) => `${user.username} ${user.email || ''} ${user.status}`.toLowerCase().includes(query));
  }, [accounts, accountQuery]);

  const filteredRequests = useMemo(() => requests.filter((item) => {
    if (requestFilter === 'all') return true;
    if (requestFilter === 'open') return ['pending', 'accepted'].includes(item.status);
    return item.status === requestFilter;
  }), [requests, requestFilter]);

  const filteredNotifications = useMemo(() => notifications.filter((item) => {
    if (notificationFilter === 'all') return true;
    if (notificationFilter === 'problem') return ['pending', 'retry', 'sending', 'failed'].includes(item.status);
    return item.status === notificationFilter;
  }), [notifications, notificationFilter]);

  async function refreshAccounts() {
    const response = await api.adminListUsers();
    setAccounts(response.users);
    setAccountStats(response.stats);
    setUpstreamAvailable(response.upstreamAvailable);
  }

  async function createAccount() {
    if (!newUser.username.trim() || !newUser.password) {
      setMessage('请填写用户名和初始密码。');
      return;
    }
    setBusy('create-account');
    try {
      await api.adminCreateUser({
        username: newUser.username.trim(),
        password: newUser.password,
        durationDays: newUser.durationDays,
      });
      setNewUser({ username: '', password: '', durationDays: 30 });
      await refreshAccounts();
      setMessage('账号已创建。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '账号创建失败。');
    } finally {
      setBusy('');
    }
  }

  function resetAccountPassword(user: AdminUser) {
    setActionDialog({
      title: `重置 ${user.username} 的密码`,
      body: '新密码会同步到媒体服务器。提交后旧密码立即失效。',
      confirmText: '确认重置',
      fields: [{ name: 'password', label: '新密码', type: 'password', required: true }],
      onSubmit: async ({ password }) => {
        setActionDialog(null);
        await performPasswordReset(user, password);
      },
    });
  }

  async function performPasswordReset(user: AdminUser, password: string) {
    setBusy(`password-${user.id}`);
    try {
      await api.adminSetUserPassword(user.id, password);
      setMessage(`已重置 ${user.username} 的密码。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '密码重置失败。');
    } finally {
      setBusy('');
    }
  }

  function extendAccount(user: AdminUser) {
    setActionDialog({
      title: `为 ${user.username} 续期`,
      body: '续期以当前有效期为基准；已过期账号从现在开始计算。',
      confirmText: '确认续期',
      fields: [{ name: 'days', label: '增加天数', type: 'number', initial: '30', required: true, min: 1, max: 3650 }],
      onSubmit: async ({ days }) => {
        setActionDialog(null);
        await performAccountExtension(user, Number.parseInt(days, 10));
      },
    });
  }

  async function performAccountExtension(user: AdminUser, days: number) {
    if (!Number.isInteger(days) || days < 1 || days > 3650) {
      setMessage('有效天数必须是 1-3650 的整数。');
      return;
    }
    setBusy(`expiry-${user.id}`);
    try {
      await api.adminSetUserExpiry(user.id, { extendDays: days });
      await refreshAccounts();
      setMessage(`已为 ${user.username} 增加 ${days} 天。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '有效期更新失败。');
    } finally {
      setBusy('');
    }
  }

  function toggleAccount(user: AdminUser) {
    const action = user.status === 'disabled' ? 'enable' : 'disable';
    setActionDialog({
      title: `${action === 'enable' ? '启用' : '停用'}账号`,
      body: `${user.username} 将${action === 'enable' ? '恢复使用权限' : '无法继续访问媒体库'}。`,
      confirmText: `确认${action === 'enable' ? '启用' : '停用'}`,
      danger: action === 'disable',
      onSubmit: async () => {
        setActionDialog(null);
        await performAccountToggle(user, action);
      },
    });
  }

  async function performAccountToggle(user: AdminUser, action: 'enable' | 'disable') {
    setBusy(`status-${user.id}`);
    try {
      await api.adminSetUserStatus(user.id, action);
      await refreshAccounts();
      setMessage(`已${action === 'enable' ? '启用' : '停用'} ${user.username}。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '账号状态更新失败。');
    } finally {
      setBusy('');
    }
  }

  function deleteAccount(user: AdminUser) {
    setActionDialog({
      title: `删除账号 ${user.username}`,
      body: '此操作会停用 Portal 账号并移除媒体服务器访问。Portal 中的账号、积分、工单、绑定与审计历史仍会保留，且该用户名以后不能重新注册。请输入用户名确认。',
      confirmText: '停用并移除访问',
      danger: true,
      fields: [{ name: 'confirmation', label: `输入 ${user.username}`, required: true }],
      onSubmit: async ({ confirmation }) => {
        if (confirmation !== user.username) {
          setMessage('用户名不匹配，未执行删除。');
          return;
        }
        setActionDialog(null);
        await performAccountDeletion(user);
      },
    });
  }

  async function performAccountDeletion(user: AdminUser) {
    setBusy(`delete-${user.id}`);
    try {
      await api.adminDeleteUser(user.id);
      await refreshAccounts();
      setMessage(`已删除账号 ${user.username}。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '账号删除失败。');
    } finally {
      setBusy('');
    }
  }

  async function previewBulkExpiry() {
    setBusy('bulk-preview');
    try {
      const response = await api.adminBulkExtendUserExpiryPreview({ extendDays: bulkDays });
      setBulkPreview(response);
      setMessage(`预计为 ${response.summary.affected} 个账号增加 ${bulkDays} 天。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '批量补偿预览失败。');
    } finally {
      setBusy('');
    }
  }

  function applyBulkExpiry() {
    if (!bulkPreview) return;
    setActionDialog({
      title: '确认批量补偿',
      body: `将给 ${bulkPreview.summary.affected} 个账号增加 ${bulkDays} 天。原因：${bulkReason.trim() || '未填写'}。`,
      confirmText: '确认执行',
      onSubmit: async () => {
        setActionDialog(null);
        await performBulkExpiry();
      },
    });
  }

  async function performBulkExpiry() {
    setBusy('bulk-apply');
    try {
      if (!bulkPreview) throw new Error('批量预览已失效，请重新预览。');
      const response = await api.adminBulkExtendUserExpiry({
        extendDays: bulkDays,
        reason: bulkReason.trim() || undefined,
        previewToken: bulkPreview.previewToken,
        operationId: bulkPreview.operationId,
      });
      setBulkPreview(null);
      await refreshAccounts();
      setMessage(`批量补偿完成：更新 ${response.summary.updated} 个账号。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '批量补偿失败。');
    } finally {
      setBusy('');
    }
  }

  async function createCodes() {
    setBusy('create-codes');
    try {
      const response = await api.createCodes(codeForm);
      setCodes([...response.codes, ...codes]);
      setMessage(`已生成 ${response.codes.length} 个卡密。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '卡密生成失败。');
    } finally {
      setBusy('');
    }
  }

  async function toggleCode(code: CodeRecord) {
    const status = code.status === 'disabled' ? 'active' : 'disabled';
    setBusy(`code-${code.id}`);
    try {
      const response = await api.updateCodeStatus(code.id, status);
      setCodes(codes.map((item) => item.id === code.id ? response.code : item));
      setMessage(`卡密已${status === 'active' ? '启用' : '禁用'}。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '卡密状态更新失败。');
    } finally {
      setBusy('');
    }
  }

  function deleteCode(code: CodeRecord) {
    setActionDialog({
      title: '删除未使用卡密',
      body: `即将删除 ${code.code}。已有兑换记录的卡密会被服务端拒绝删除。`,
      confirmText: '确认删除',
      danger: true,
      onSubmit: async () => {
        setActionDialog(null);
        await performCodeDeletion(code);
      },
    });
  }

  async function performCodeDeletion(code: CodeRecord) {
    setBusy(`delete-code-${code.id}`);
    try {
      await api.deleteCode(code.id);
      setCodes(codes.filter((item) => item.id !== code.id));
      setMessage('卡密已删除。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '卡密删除失败。');
    } finally {
      setBusy('');
    }
  }

  async function refreshOperations() {
    const results = await Promise.allSettled([
      api.adminOperationsOverview(), api.adminRequests(), api.adminNotifications(), api.adminMemberships(), api.adminAudit(50),
    ]);
    if (results[0].status === 'fulfilled') setOperationsOverview(results[0].value);
    if (results[1].status === 'fulfilled') setRequests(results[1].value.items);
    if (results[2].status === 'fulfilled') setNotifications(results[2].value.items);
    if (results[3].status === 'fulfilled') setMemberships(results[3].value.items);
    if (results[4].status === 'fulfilled') setAudit(results[4].value.items);
    const failed = results.filter((result) => result.status === 'rejected').length;
    if (failed) throw new Error(`有 ${failed} 个运营模块刷新失败，已保留其旧数据。`);
  }

  async function runRefresh(key: string, action: () => Promise<void>, fallback: string) {
    setBusy(key);
    try {
      await action();
      setMessage('刷新完成。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : fallback);
    } finally {
      setBusy('');
    }
  }

  function updateMediaRequest(item: MediaRequestRecord, status: 'accepted' | 'available' | 'rejected') {
    const labels = { accepted: '受理', available: '标记为已上架', rejected: '拒绝' };
    setActionDialog({
      title: `${labels[status]}《${item.title}》`,
      body: '状态更新后，已绑定 Telegram 的用户会收到通知。',
      confirmText: `确认${labels[status]}`,
      danger: status === 'rejected',
      fields: [{ name: 'note', label: '管理员备注（可留空）', type: 'textarea', initial: item.adminNote || '' }],
      onSubmit: async ({ note }) => {
        setActionDialog(null);
        await performMediaRequestUpdate(item, status, note.trim() || undefined);
      },
    });
  }

  async function performMediaRequestUpdate(item: MediaRequestRecord, status: 'accepted' | 'available' | 'rejected', note?: string) {
    setBusy(`request-${item.id}`);
    try {
      const response = await api.adminUpdateRequest(item.id, status, note);
      setRequests((current) => current.map((entry) => entry.id === item.id ? response.item : entry));
      setOperationsOverview(await api.adminOperationsOverview());
      setMessage('工单状态已更新，已绑定 Telegram 的用户会收到通知。');
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          const latest = await api.adminRequests();
          setRequests(latest.items);
          setMessage('该工单已由其他管理员处理，列表已刷新。');
          return;
        } catch {
          setMessage('该工单状态已变化，请刷新后查看最新处理结果。');
          return;
        }
      }
      setMessage(error instanceof Error ? error.message : '工单更新失败。');
    } finally {
      setBusy('');
    }
  }

  async function retryNotification(item: AdminNotification) {
    setBusy(`notification-${item.id}`);
    try {
      const result = await api.adminRetryNotification(item.id, item.version);
      setNotifications((current) => current.map((entry) => entry.id === item.id ? { ...entry, status: 'retry', version: result.version, claimedAt: null, lastError: null } : entry));
      setMessage('通知已重新进入发送队列。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '通知重试失败。');
    } finally {
      setBusy('');
    }
  }

  async function previewBroadcast() {
    if (!broadcastMessage.trim()) {
      setMessage('请先填写广播内容。');
      return;
    }
    setBusy('broadcast-preview');
    try {
      const result = await api.adminPreviewBroadcast(broadcastAudience);
      setBroadcastPreview(result);
      setMessage(`广播预览完成：将向 ${result.count} 个已绑定用户发送。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '广播预览失败。');
    } finally {
      setBusy('');
    }
  }

  function sendBroadcast() {
    if (!broadcastPreview || broadcastPreview.audience !== broadcastAudience) return;
    setActionDialog({
      title: '确认广播入队',
      body: `这条消息将加入 ${broadcastPreview.count} 个用户的发送队列。发送后无法撤回。`,
      confirmText: '确认加入队列',
      danger: true,
      onSubmit: async () => {
        setActionDialog(null);
        await performBroadcast();
      },
    });
  }

  async function performBroadcast() {
    if (!broadcastPreview || broadcastPreview.audience !== broadcastAudience || broadcastInFlightRef.current) return;
    broadcastInFlightRef.current = true;
    const signature = JSON.stringify({ audience: broadcastAudience, message: broadcastMessage.trim() });
    const attempt = idempotencyAttempt(broadcastAttemptRef.current, signature);
    broadcastAttemptRef.current = attempt;
    setBusy('broadcast-send');
    try {
      const result = await api.adminCreateBroadcast({
        audience: broadcastAudience,
        message: broadcastMessage.trim(),
        confirmCount: broadcastPreview.count,
        idempotencyKey: attempt.key,
      });
      broadcastAttemptRef.current = null;
      setBroadcastMessage('');
      setBroadcastPreview(null);
      let refreshWarning = '';
      try {
        await refreshOperations();
      } catch (error) {
        refreshWarning = `；${error instanceof Error ? error.message : '后续列表刷新失败，请稍后手动刷新。'}`;
      }
      setMessage(`广播已入队，共 ${result.queued} 条；发送结果可在通知队列查看${refreshWarning}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '广播入队失败，可直接重试。');
    } finally {
      broadcastInFlightRef.current = false;
      setBusy('');
    }
  }

  async function previewInactivity() {
    setBusy('inactivity-preview');
    try {
      const result = await api.adminPreviewInactivity();
      setInactivityPreview(result);
      setMessage(`已检查 ${result.checked} 个账号，发现 ${result.candidates.length} 个停用候选；本次仅预览，不会停用账号。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '不活跃账号预览失败。');
    } finally {
      setBusy('');
    }
  }

  function adjustPoints(user: AdminUser) {
    setActionDialog({
      title: `调整 ${user.username} 的积分`,
      body: '正数增加、负数扣除；操作原因会进入审计日志。',
      confirmText: '确认调整',
      fields: [
        { name: 'amount', label: '积分变化', type: 'number', initial: '10', required: true },
        { name: 'note', label: '操作原因', required: true },
      ],
      onSubmit: async ({ amount, note }) => {
        setActionDialog(null);
        await performPointsAdjustment(user, Number.parseInt(amount, 10), note);
      },
    });
  }

  async function performPointsAdjustment(user: AdminUser, amount: number, note: string) {
    if (!Number.isInteger(amount) || amount === 0) {
      setMessage('积分调整必须是非零整数。');
      return;
    }
    if (!note.trim()) return;
    setBusy(`points-${user.id}`);
    try {
      const result = await api.adminAdjustPoints({ userId: user.id, amount, note: note.trim() });
      setMessage(`已调整 ${user.username} 的积分，当前余额 ${result.balance}。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '积分调整失败。');
    } finally {
      setBusy('');
    }
  }

  async function saveSettings() {
    if (!ready) {
      setMessage('配置尚未完整加载，已禁止保存。请刷新后重试。');
      return;
    }
    const faq = faqText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [q, ...answer] = line.split('|');
        return { q: q.trim(), a: answer.join('|').trim() };
      })
      .filter((item) => item.q && item.a);
    const timeline = timelineText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [date, ...body] = line.split('|');
        return { date: date.trim(), body: body.join('|').trim() };
      })
      .filter((item) => item.body);
    const expiryReminderDays = [...new Set(
      expiryReminderDaysText
        .split(',')
        .map((item) => Number.parseInt(item.trim(), 10))
        .filter((day) => Number.isInteger(day) && day >= 0 && day <= 365),
    )].sort((a, b) => b - a);
    const payload: Partial<PublicSettings> = {
      siteName: settings.siteName,
      tagline: settings.tagline,
      copy: {
        ...settings.copy,
        notice: settings.copy.notice.trim() || '一处安静、专注的声音栖地。',
      },
      client: {
        ...settings.client,
        iosGuideText: settings.client.iosGuideText.trim() || '在 App Store 搜索“EchoShelf”并安装。',
        desktopGuideText: settings.client.desktopGuideText.trim() || '暂无稳定方案，建议使用手机或平板。',
      },
      announcement: { ...settings.announcement, timeline },
      operations: { ...settings.operations },
      telegram: { ...settings.telegram, expiryReminderDays },
      sections: {
        ...settings.sections,
        steps: stepsText.split('\n').map((item) => item.trim()).filter(Boolean),
        faq,
      },
      features: { ...settings.features },
      links: { ...settings.links },
    };
    setBusy('save');
    setMessage('');
    try {
      const response = await api.updatePublicSettings(payload, settingsRevision);
      hydrate(response.settings);
      setSettingsRevision(response.revision);
      setMessage('设置已保存。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败，请确认管理员登录状态。');
    } finally {
      setBusy('');
    }
  }

  async function logout() {
    setBusy('logout');
    try {
      await clearSession();
    } finally {
      location.href = '/admin';
    }
  }

  const telegram = settings.telegram;

  return (
    <ShellBackdrop className="w-full px-3 pb-8 pt-5 sm:px-6 sm:pt-7">
      {busy === 'logout' && <LoadingScreen title="正在退出" subtitle="console" />}
      <NavDrawer
        active={tab}
        onSelect={setTab}
        title={settings.siteName}
        subtitle="运营管理中心"
        ariaLabel="管理台栏目导航"
        items={[
          { key: 'overview', label: '运营总览', description: '状态、任务与核心指标', icon: <Activity size={19} /> },
          { key: 'accounts', label: '账号管理', description: '账号、有效期与积分', icon: <Users size={19} /> },
          { key: 'codes', label: '卡密管理', description: '邀请码与续期码', icon: <KeyRound size={19} /> },
          { key: 'operations', label: '工单通知', description: '请求、广播与发送队列', icon: <ClipboardList size={19} />, badge: operationsOverview?.pendingRequests ? String(operationsOverview.pendingRequests) : undefined },
          { key: 'library', label: '媒体库', description: '资源与收听活动', icon: <BookOpen size={19} /> },
          { key: 'settings', label: '站点配置', description: '功能开关与页面内容', icon: <Settings2 size={19} /> },
        ]}
      />
      <div className="app-content mx-auto w-full max-w-6xl">
        <header className="sheet rounded-[20px] p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <WordMark siteName={settings.siteName} tagline="管理台" small />
            <div className="flex gap-2">
              <Button variant="secondary" loading={busy === 'logout'} onClick={logout}>
                <LogOut size={15} /> 退出
              </Button>
              {tab === 'settings' && (
                <Button variant="claret" loading={busy === 'save'} loadingText="保存中" disabled={!ready} onClick={saveSettings}>
                  <Save size={15} /> 保存设置
                </Button>
              )}
            </div>
          </div>
          <div className="mt-5 flex items-start gap-3 rounded-[16px] border border-[rgba(0,190,227,.22)] bg-[rgba(0,190,227,.08)] p-4">
            <Settings2 className="mt-0.5 shrink-0 text-[var(--primary)]" size={18} />
            <p className="text-sm leading-6 text-[var(--muted-foreground)]">
              Web 管理端负责账号 CRUD、卡密、批量补偿和站点配置；Telegram Bot 负责移动端用户状态操作与工单处理，不再生成卡密。
            </p>
          </div>
        </header>

        {message && (
          <div className="mt-4">
            <StatusNote tone={message.includes('失败') || message.includes('禁止') ? 'warning' : 'success'}>{message}</StatusNote>
          </div>
        )}

        {tab === 'overview' && (
          <div className="mt-5 grid gap-5">
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <SectionHeader eyebrow="运营总览" title="账号与自动化状态" body="集中查看账号、工单、通知、群组和后台任务是否正常。" />
                <Button variant="secondary" loading={busy === 'refresh-operations'} onClick={() => void runRefresh('refresh-operations', refreshOperations, '运营数据刷新失败。')}><RefreshCcw size={15} /> 刷新</Button>
              </div>
              <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatCard label="正常账号" value={operationsOverview?.users.active ?? 0} />
                <StatCard label="待处理工单" value={operationsOverview?.pendingRequests ?? 0} />
                <StatCard label="失败通知" value={operationsOverview?.notifications.failed ?? 0} />
                <StatCard label="退群宽限" value={operationsOverview?.groupGrace ?? 0} />
              </div>
            </Sheet>
            <div className="grid gap-5 lg:grid-cols-3">
              <Panel className="rounded-[20px] p-5"><p className="text-sm text-[var(--muted-foreground)]">后台任务</p><p className="mt-2 font-display text-2xl font-semibold">{operationsOverview?.worker.healthy ? '运行正常' : '需要检查'}</p><p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">{operationsOverview?.worker.healthy ? `最近心跳延迟 ${Math.round(operationsOverview.worker.lagSeconds || 0)} 秒` : operationsOverview?.worker.reason || '尚无状态'}</p></Panel>
              <Panel className="rounded-[20px] p-5"><p className="text-sm text-[var(--muted-foreground)]">积分与邀请</p><p className="mt-2 font-display text-2xl font-semibold">{operationsOverview?.pointAccounts ?? 0} 个积分账号</p><p className="mt-2 text-xs text-[var(--muted-foreground)]">累计生成邀请 {operationsOverview?.referrals ?? 0} 个</p></Panel>
              <Panel className="rounded-[20px] p-5"><p className="text-sm text-[var(--muted-foreground)]">媒体库同步</p><p className="mt-2 font-display text-2xl font-semibold">{library?.stats.libraryCount ?? 0} 个媒体库</p><p className="mt-2 text-xs text-[var(--muted-foreground)]">{library?.stats.activeUserCount ?? 0}/{library?.stats.upstreamUserCount ?? 0} 个上游账号启用</p></Panel>
            </div>
            <Panel className="rounded-[20px] p-5">
              <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-display text-lg font-semibold">不活跃账号策略</p><p className="mt-1 text-sm text-[var(--muted-foreground)]">当前为{settings.operations.inactivityAutoDisable ? '自动停用' : '仅监控'}，阈值 {settings.operations.inactiveDays} 天，新账号宽限 {settings.operations.newUserGraceDays} 天。</p></div><Button variant="secondary" loading={busy === 'inactivity-preview'} onClick={previewInactivity}>立即预览</Button></div>
            </Panel>
          </div>
        )}

        {tab === 'accounts' && (
          <div className="mt-5 grid gap-5">
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <SectionHeader eyebrow="账号管理" title="Portal 与媒体账号" body="创建、启停、改密、调整有效期及删除账号。" />
                <Button variant="secondary" loading={busy === 'refresh-accounts'} onClick={() => void runRefresh('refresh-accounts', refreshAccounts, '账号列表刷新失败。')}><RefreshCcw size={15} /> 刷新</Button>
              </div>
              {!upstreamAvailable && <div className="mt-4"><StatusNote tone="warning">媒体服务器暂时不可用，部分同步状态可能不准确。</StatusNote></div>}
              <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard label="全部" value={accountStats.total} />
                <StatCard label="正常" value={accountStats.active} />
                <StatCard label="已到期" value={accountStats.expired} />
                <StatCard label="已停用" value={accountStats.disabled} />
              </div>
            </Sheet>

            <div className="grid gap-5 lg:grid-cols-2">
              <Panel className="rounded-[20px] p-5">
                <h3 className="font-display text-lg font-semibold"><UserPlus className="mr-2 inline" size={18} />创建账号</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <Text label="用户名" value={newUser.username} maxLength={18} onChange={(value) => setNewUser({ ...newUser, username: value })} />
                  <Text label="初始密码（6–18 位）" type="password" minLength={6} maxLength={18} value={newUser.password} onChange={(value) => setNewUser({ ...newUser, password: value })} />
                  <NumberInput label="有效天数（0 为永久）" value={newUser.durationDays} min={0} max={3650} onChange={(value) => setNewUser({ ...newUser, durationDays: value })} />
                </div>
                <Button variant="claret" className="mt-5 w-full" loading={busy === 'create-account'} loadingText="创建中" onClick={createAccount}><UserPlus size={15} /> 创建账号</Button>
              </Panel>

              <Panel className="rounded-[20px] p-5">
                <h3 className="font-display text-lg font-semibold"><CalendarClock className="mr-2 inline" size={18} />批量补偿有效期</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <NumberInput label="增加天数" value={bulkDays} min={1} max={3650} onChange={(value) => { setBulkDays(value); setBulkPreview(null); }} />
                  <Text label="操作备注" value={bulkReason} onChange={setBulkReason} />
                </div>
                {bulkPreview && (
                  <div className="mt-4 rounded-xl border border-[rgba(0,190,227,.25)] bg-[rgba(0,190,227,.08)] p-4 text-sm leading-6">
                    预计修改 <b>{bulkPreview.summary.affected}</b> 个账号；其中可恢复到期账号 <b>{bulkPreview.summary.reactivatable}</b> 个，跳过管理员 <b>{bulkPreview.summary.skippedAdmins}</b> 个。
                  </div>
                )}
                <div className="mt-5 grid grid-cols-2 gap-2">
                  <Button variant="secondary" loading={busy === 'bulk-preview'} onClick={previewBulkExpiry}>预览范围</Button>
                  <Button variant="claret" loading={busy === 'bulk-apply'} disabled={!bulkPreview} onClick={applyBulkExpiry}>确认补偿</Button>
                </div>
              </Panel>
            </div>

            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <h3 className="font-display text-xl font-semibold">账号列表</h3>
                <label className="relative block w-full sm:w-72"><Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]" size={16} /><input className="field pl-10" value={accountQuery} onChange={(event) => setAccountQuery(event.target.value)} placeholder="搜索用户名、邮箱或状态" /></label>
              </div>
              <div className="mt-5 grid gap-3">
                {filteredAccounts.map((user) => (
                  <div key={user.id} className="rounded-[16px] border border-[rgba(231,246,253,.14)] bg-[rgba(255,255,255,.05)] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2"><b>{user.username}</b><StatusPill user={user} /></div>
                        <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">有效期：{user.expiresAt ? formatShanghaiDateTime(user.expiresAt) : '永久'} · 媒体端：{user.upstreamFound ? (user.upstreamActive ? '启用' : '停用') : '未找到'}</p>
                      </div>
                      {user.role === 'user' ? (
                        <div className="flex flex-wrap gap-2">
                          <SmallButton onClick={() => void resetAccountPassword(user)}>改密</SmallButton>
                          <SmallButton onClick={() => void extendAccount(user)}>续期</SmallButton>
                          <SmallButton onClick={() => void adjustPoints(user)}>积分</SmallButton>
                          <SmallButton onClick={() => void toggleAccount(user)}><Power size={13} />{user.status === 'disabled' ? '启用' : '停用'}</SmallButton>
                          <SmallButton danger onClick={() => void deleteAccount(user)}><Trash2 size={13} />删除</SmallButton>
                        </div>
                      ) : <span className="text-xs text-[var(--muted-foreground)]">管理员账号受保护</span>}
                    </div>
                  </div>
                ))}
                {!filteredAccounts.length && <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">没有匹配的账号。</p>}
              </div>
            </Sheet>
          </div>
        )}

        {tab === 'codes' && (
          <div className="mt-5 grid gap-5">
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <SectionHeader eyebrow="卡密管理" title="邀请码与续期码" body="卡密统一在 Web 端生成、启停和删除，Telegram Bot 不提供生成命令。" />
              <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Select label="类型" value={codeForm.type} onChange={(value) => setCodeForm({ ...codeForm, type: value })} options={[["register", "注册邀请码"], ["renew", "续期码"]]} />
                <NumberInput label="有效天数" value={codeForm.durationDays} min={0} max={3650} onChange={(value) => setCodeForm({ ...codeForm, durationDays: value })} />
                <NumberInput label="生成数量" value={codeForm.count} min={1} max={100} onChange={(value) => setCodeForm({ ...codeForm, count: value })} />
                <NumberInput label="每码总次数" value={codeForm.maxUses} min={1} max={10000} onChange={(value) => setCodeForm({ ...codeForm, maxUses: value })} />
                <NumberInput label="每用户最多次数" value={codeForm.perUserMaxUses} min={1} max={10000} onChange={(value) => setCodeForm({ ...codeForm, perUserMaxUses: value })} />
                <Text label="指定用户名（可空）" value={codeForm.designatedUsername} onChange={(value) => setCodeForm({ ...codeForm, designatedUsername: value })} />
                <Text label="失效时间（可空）" type="datetime-local" value={codeForm.expiresAt} onChange={(value) => setCodeForm({ ...codeForm, expiresAt: value })} />
                <Text label="备注（可空）" value={codeForm.note} onChange={(value) => setCodeForm({ ...codeForm, note: value })} />
                <div className="flex items-end"><Button variant="claret" className="w-full" loading={busy === 'create-codes'} loadingText="生成中" onClick={createCodes}><KeyRound size={15} /> 生成卡密</Button></div>
              </div>
            </Sheet>

            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex items-center justify-between gap-4"><h3 className="font-display text-xl font-semibold">卡密列表</h3><Button variant="secondary" loading={busy === 'refresh-codes'} onClick={() => void runRefresh('refresh-codes', async () => setCodes((await api.listCodes()).codes), '卡密列表刷新失败。')}><RefreshCcw size={15} /> 刷新</Button></div>
              <div className="mt-5 grid gap-3">
                {codes.map((code) => (
                  <div key={code.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[16px] border border-[rgba(231,246,253,.14)] bg-[rgba(255,255,255,.05)] p-4">
                    <div className="min-w-0"><p className="break-all font-mono font-semibold">{code.code}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{code.type === 'register' ? '注册邀请码' : '续期码'} · {code.durationDays === 0 ? '永久' : `${code.durationDays} 天`} · 已用 {code.usedCount}/{code.maxUses} · {code.status === 'active' ? '启用' : '停用'}</p></div>
                    <div className="flex flex-wrap gap-2">
                      <SmallButton onClick={() => void navigator.clipboard.writeText(code.code)}><Copy size={13} />复制</SmallButton>
                      <SmallButton onClick={() => void toggleCode(code)}>{code.status === 'active' ? '禁用' : '启用'}</SmallButton>
                      <SmallButton danger onClick={() => void deleteCode(code)}><Trash2 size={13} />删除</SmallButton>
                    </div>
                  </div>
                ))}
                {!codes.length && <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">暂无卡密。</p>}
              </div>
            </Sheet>
          </div>
        )}

        {tab === 'operations' && (
          <div className="mt-5 grid gap-5">
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4"><SectionHeader eyebrow="工单管理" title="有声书请求" body="受理、完成或拒绝用户请求；状态会同步到 Web，并通知已绑定 Telegram 的用户。" /><div className="flex gap-2"><select className="field !min-h-10 !w-auto" value={requestFilter} onChange={(event) => setRequestFilter(event.target.value)}><option value="open">待处理</option><option value="pending">新提交</option><option value="accepted">已受理</option><option value="available">已上架</option><option value="rejected">未采纳</option><option value="all">全部</option></select><Button variant="secondary" loading={busy === 'refresh-operations'} onClick={() => void runRefresh('refresh-operations', refreshOperations, '运营数据刷新失败。')}><RefreshCcw size={15} /> 刷新全部</Button></div></div>
              <div className="mt-6 grid gap-3">
                {filteredRequests.map((item) => (
                  <Panel key={item.id} className="rounded-[16px] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-display text-lg font-semibold">{item.title}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{item.username || '未知用户'} · {formatShanghaiDateTime(item.createdAt)}</p></div><span className="rounded-full tag-gold px-3 py-1 text-xs font-semibold">{requestStatusText[item.status] || item.status}</span></div>
                    {item.details && <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{item.details}</p>}
                    {item.adminNote && <p className="mt-3 rounded-xl bg-white/5 p-3 text-sm">处理结果：{item.adminNote}</p>}
                    {['pending', 'accepted'].includes(item.status) ? (
                      <div className="mt-4 flex flex-wrap gap-2"><SmallButton onClick={() => void updateMediaRequest(item, 'accepted')}>受理</SmallButton><SmallButton onClick={() => void updateMediaRequest(item, 'available')}>已上架</SmallButton><SmallButton danger onClick={() => void updateMediaRequest(item, 'rejected')}>拒绝</SmallButton></div>
                    ) : (
                      <p className="mt-4 text-xs text-[var(--muted-foreground)]">该工单已结束，不再提供处理操作。</p>
                    )}
                  </Panel>
                ))}
                {!filteredRequests.length && <p className="py-7 text-center text-sm text-[var(--muted-foreground)]">当前筛选下暂无内容请求。</p>}
              </div>
            </Sheet>

            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <SectionHeader eyebrow="消息触达" title="Telegram 通知广播" body="先预览接收人数，再确认加入可靠通知队列；失败消息可在下方重试，所有广播均写入审计记录。" />
              <div className="mt-6 grid gap-4 lg:grid-cols-[.35fr_1fr]">
                <Select label="接收范围" value={broadcastAudience} onChange={(value) => { setBroadcastAudience(value as BroadcastAudience); setBroadcastPreview(null); }} options={[["active", "正常账号"], ["expiring_7d", "7 天内到期"], ["expired", "已到期账号"], ["all_bound", "全部已绑定账号"]]} />
                <Textarea label="广播内容" compact value={broadcastMessage} onChange={(value) => { setBroadcastMessage(value); setBroadcastPreview(null); }} />
              </div>
              {broadcastPreview && <div className="mt-4"><StatusNote tone={broadcastPreview.count ? 'warning' : 'neutral'}>接收人数：{broadcastPreview.count}；抽样账号：{broadcastPreview.sample.join('、') || '无'}。消息尚未发送。</StatusNote></div>}
              <div className="mt-5 grid gap-2 sm:grid-cols-2"><Button variant="secondary" loading={busy === 'broadcast-preview'} onClick={previewBroadcast}>预览接收人</Button><Button variant="claret" loading={busy === 'broadcast-send'} disabled={!broadcastPreview?.count} onClick={sendBroadcast}>确认加入发送队列</Button></div>
            </Sheet>

            <div className="grid gap-5 lg:grid-cols-2">
              <Sheet className="rounded-[20px] p-6 sm:p-7">
                <div className="flex items-center justify-between gap-3"><h3 className="font-display text-xl font-semibold"><Bell className="mr-2 inline" size={19} />通知队列</h3><select className="field !min-h-10 !w-auto" value={notificationFilter} onChange={(event) => setNotificationFilter(event.target.value)}><option value="problem">待发 / 异常</option><option value="failed">失败</option><option value="retry">重试中</option><option value="pending">待发送</option><option value="sent">已发送</option><option value="all">全部</option></select></div>
                <div className="mt-5 grid gap-3">
                  {filteredNotifications.slice(0, 30).map((item) => (
                    <Panel key={item.id} className="rounded-[14px] p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate font-semibold">{item.kind}</p><p className="mt-1 line-clamp-2 text-xs text-[var(--muted-foreground)]">{item.message}</p></div><span className="text-xs">{item.status}</span></div>{item.lastError && <p className="mt-2 text-xs text-red-300">{item.lastError}</p>}{['failed', 'retry'].includes(item.status) && <div className="mt-3"><SmallButton onClick={() => void retryNotification(item)}>重新发送</SmallButton></div>}{item.status === 'sending' && <p className="mt-2 text-xs text-amber-200">正在发送中，不能手工重试；过期 claim 将由安全恢复流程处理。</p>}</Panel>
                  ))}
                  {!filteredNotifications.length && <p className="py-7 text-center text-sm text-[var(--muted-foreground)]">当前筛选下暂无通知记录。</p>}
                </div>
              </Sheet>

              <Sheet className="rounded-[20px] p-6 sm:p-7">
                <h3 className="font-display text-xl font-semibold">群组资格</h3>
                <div className="mt-5 grid gap-3">
                  {memberships.map((item) => <Panel key={item.id} className="rounded-[14px] p-4"><div className="flex items-center justify-between gap-3"><p className="font-semibold">{item.username}</p><span className="text-xs">{membershipStatusText[item.status] || item.status}</span></div><p className="mt-2 text-xs text-[var(--muted-foreground)]">TG {item.telegramId} · 检查于 {formatShanghaiDateTime(item.lastCheckedAt)}</p>{item.graceExpiresAt && <p className="mt-1 text-xs text-amber-200">宽限至 {formatShanghaiDateTime(item.graceExpiresAt)}</p>}</Panel>)}
                  {!memberships.length && <p className="py-7 text-center text-sm text-[var(--muted-foreground)]">暂无群组资格记录。</p>}
                </div>
              </Sheet>
            </div>

            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <h3 className="font-display text-xl font-semibold">最近审计记录</h3>
              <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead className="text-[var(--muted-foreground)]"><tr><th className="pb-3">时间</th><th className="pb-3">操作者</th><th className="pb-3">动作</th><th className="pb-3">对象</th></tr></thead><tbody>{audit.map((item) => <tr key={item.id} className="border-t border-white/10"><td className="py-3">{formatShanghaiDateTime(item.createdAt)}</td><td className="py-3">{item.actor || 'system'}</td><td className="py-3 font-mono text-xs">{item.action}</td><td className="py-3 text-xs">{item.targetType || '-'} {item.targetId || ''}</td></tr>)}</tbody></table></div>
            </Sheet>
          </div>
        )}

        {tab === 'library' && (
          <div className="mt-5 grid gap-5">
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4"><SectionHeader eyebrow="媒体库" title="ABS 实时概览" body="查看媒体库、上游账号收听进度和不活跃候选。" /><Button variant="secondary" loading={busy === 'refresh-library'} onClick={() => void runRefresh('refresh-library', async () => setLibrary(await api.adminLibraryOverview()), '媒体库刷新失败。')}><RefreshCcw size={15} /> 刷新</Button></div>
              <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4"><StatCard label="媒体库" value={library?.stats.libraryCount ?? 0} /><StatCard label="上游账号" value={library?.stats.upstreamUserCount ?? 0} /><StatCard label="进度记录" value={library?.stats.progressCount ?? 0} /><StatCard label="不活跃候选" value={library?.stats.inactiveCandidateCount ?? 0} /></div>
              <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{library?.libraries.map((item) => <Panel key={item.id} className="rounded-[14px] p-4"><p className="font-display font-semibold">{item.name}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{item.mediaType} · 扫描：{item.lastScan ? formatShanghaiDateTime(item.lastScan) : '未知'}</p></Panel>)}</div>
            </Sheet>
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex items-center justify-between gap-3"><h3 className="font-display text-xl font-semibold">账号收听活动</h3><Button variant="secondary" loading={busy === 'inactivity-preview'} onClick={previewInactivity}>停用预览</Button></div>
              {inactivityPreview && <div className="mt-4"><StatusNote tone={inactivityPreview.candidates.length ? 'warning' : 'success'}>检查 {inactivityPreview.checked} 个账号，候选 {inactivityPreview.candidates.length} 个。本次操作仅预览。</StatusNote></div>}
              <div className="mt-5 grid gap-3">{library?.users.map((item) => <Panel key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[14px] p-4"><div><div className="flex items-center gap-2"><p className="font-semibold">{item.username}</p>{item.inactivityCandidate && <span className="rounded-full tag-claret px-2 py-0.5 text-[10px]">候选停用</span>}</div><p className="mt-1 text-xs text-[var(--muted-foreground)]">最近收听：{item.latestListenAt ? formatShanghaiDateTime(item.latestListenAt) : '无记录'} · 进度 {item.progressCount} 条</p></div><span className="text-xs">{item.isActive ? '上游启用' : '上游停用'} / {item.portalStatus || '未绑定'}</span></Panel>)}</div>
            </Sheet>
          </div>
        )}

        {tab === 'settings' && <div className="mt-5 grid gap-5">
          <Sheet className="rounded-[20px] p-6 sm:p-7">
            <SectionHeader eyebrow="站点配置" title="页面内容与入口" body="维护公开页面、客户端连接信息和展示开关。" />
            <div className="mt-6 grid gap-5 lg:grid-cols-2">
              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">品牌与首页</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <Text label="站点名称" value={settings.siteName} onChange={(value) => setSettings({ ...settings, siteName: value })} />
                  <Text label="站点副标题" value={settings.tagline} onChange={(value) => setSettings({ ...settings, tagline: value })} />
                  <Text label="首页眉题" value={settings.copy.heroKicker} onChange={(value) => setSettings({ ...settings, copy: { ...settings.copy, heroKicker: value } })} />
                  <Text label="首页主标题" value={settings.copy.heroTitle} onChange={(value) => setSettings({ ...settings, copy: { ...settings.copy, heroTitle: value } })} />
                  <Text label="首页副标题" value={settings.copy.heroSubtitle} onChange={(value) => setSettings({ ...settings, copy: { ...settings.copy, heroSubtitle: value } })} />
                </div>
                <div className="mt-4"><Textarea label="首页说明" compact value={settings.copy.notice} onChange={(value) => setSettings({ ...settings, copy: { ...settings.copy, notice: value } })} /></div>
              </Panel>

              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">客户端与链接</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <UrlField label="听书服务器地址" value={settings.client.serverUrl} onChange={(value) => setSettings({ ...settings, client: { ...settings.client, serverUrl: value } })} />
                  <UrlField label="Android 安装包" optional value={settings.client.androidDownloadUrl} onChange={(value) => setSettings({ ...settings, client: { ...settings.client, androidDownloadUrl: value } })} />
                  <UrlField label="客服链接" optional value={settings.links.supportUrl} onChange={(value) => setSettings({ ...settings, links: { ...settings.links, supportUrl: value } })} />
                  <UrlField label="公告入口" optional value={settings.links.announcementUrl} onChange={(value) => setSettings({ ...settings, links: { ...settings.links, announcementUrl: value } })} />
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <Textarea label="iPhone / iPad 说明" compact value={settings.client.iosGuideText} onChange={(value) => setSettings({ ...settings, client: { ...settings.client, iosGuideText: value } })} />
                  <Textarea label="电脑端说明" compact value={settings.client.desktopGuideText} onChange={(value) => setSettings({ ...settings, client: { ...settings.client, desktopGuideText: value } })} />
                </div>
              </Panel>

              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">公开页面开关</h3>
                <div className="mt-3">
                  <Check label="开放网站自助注册" checked={settings.features.registration} onChange={(value) => setSettings({ ...settings, features: { ...settings.features, registration: value } })} />
                  <Check label="显示客服入口" checked={settings.features.showSupportEntry} onChange={(value) => setSettings({ ...settings, features: { ...settings.features, showSupportEntry: value } })} />
                  <Check label="显示公告入口" checked={settings.features.showAnnouncements} onChange={(value) => setSettings({ ...settings, features: { ...settings.features, showAnnouncements: value } })} />
                </div>
              </Panel>

              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">教程内容</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <Textarea label="开始步骤（每行一条）" value={stepsText} onChange={setStepsText} />
                  <Textarea label="常见问题（问题|答案）" value={faqText} onChange={setFaqText} />
                </div>
              </Panel>

              <Panel className="rounded-[16px] p-5 lg:col-span-2">
                <h3 className="font-display text-lg font-semibold">不活跃账号自动治理</h3>
                <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">后台任务会按收听活动判断普通账号；管理员、永久账号、新注册宽限期账号不会被误停。建议先在“媒体库”页预览候选。</p>
                <div className="mt-3"><Check label="自动停用长期无收听活动的账号" checked={settings.operations.inactivityAutoDisable} onChange={(value) => setSettings({ ...settings, operations: { ...settings.operations, inactivityAutoDisable: value } })} /></div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <NumberInput label="不活跃阈值（天）" value={settings.operations.inactiveDays} min={7} max={3650} onChange={(value) => setSettings({ ...settings, operations: { ...settings.operations, inactiveDays: value } })} />
                  <NumberInput label="新账号宽限（天）" value={settings.operations.newUserGraceDays} min={0} max={365} onChange={(value) => setSettings({ ...settings, operations: { ...settings.operations, newUserGraceDays: value } })} />
                </div>
                <p className="mt-4 text-xs text-[var(--muted-foreground)]">上次检查：{settings.operations.lastInactivityCheckAt ? formatShanghaiDateTime(settings.operations.lastInactivityCheckAt) : '尚未运行'} · 上次停用 {settings.operations.lastInactivityDisabled} 个</p>
              </Panel>
            </div>
          </Sheet>

          <Sheet className="rounded-[20px] p-6 sm:p-7">
            <SectionHeader eyebrow="Telegram" title="Bot 功能开关" body="Bot 负责移动端状态操作与工单；这里控制功能是否开放及必要规则。" />
            <div className="mt-6 grid gap-5 lg:grid-cols-2">
              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">账号与消息</h3>
                <div className="mt-3">
                  <Check label="开放账号续期" checked={telegram.renewalEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, renewalEnabled: value } })} />
                  <Check label="开放一次性密码重置" checked={telegram.passwordResetEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, passwordResetEnabled: value } })} />
                  <Check label="显示最近收听" checked={telegram.recentListeningEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, recentListeningEnabled: value } })} />
                  <Check label="显示公告入口" checked={telegram.announcementsEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, announcementsEnabled: value } })} />
                  <Check label="发送账号到期提醒" checked={telegram.lifecycleNotificationsEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, lifecycleNotificationsEnabled: value } })} />
                </div>
                <div className="mt-4"><Text label="到期提醒天数（逗号分隔）" value={expiryReminderDaysText} onChange={setExpiryReminderDaysText} /></div>
              </Panel>

              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">管理与社群</h3>
                <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">管理员 ID 仍需通过服务器环境变量 TELEGRAM_ADMIN_IDS 授权。</p>
                <div className="mt-3">
                  <Check label="开放 Bot 管理台" checked={telegram.adminEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, adminEnabled: value } })} />
                  <Check label="启用必需群组资格同步" checked={telegram.groupMembershipEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, groupMembershipEnabled: value } })} />
                  <Check label="开放求有声书工单" checked={telegram.requestsEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, requestsEnabled: value } })} />
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <Text label="必需群组 ID" value={telegram.requiredGroupId} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, requiredGroupId: value } })} />
                  <UrlField label="群组邀请链接" optional value={telegram.requiredGroupInviteUrl} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, requiredGroupInviteUrl: value } })} />
                  <NumberInput label="退群宽限小时" value={telegram.groupGraceHours} min={1} max={720} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, groupGraceHours: value } })} />
                </div>
              </Panel>

              <Panel className="rounded-[16px] p-5 lg:col-span-2">
                <h3 className="font-display text-lg font-semibold">签到、积分与邀请</h3>
                <div className="mt-4 grid gap-5 lg:grid-cols-[.8fr_1.2fr]">
                  <div>
                    <Check label="开放每日签到" checked={telegram.checkinEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, checkinEnabled: value } })} />
                    <Check label="开放积分兑换有效期" checked={telegram.pointsRedemptionEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, pointsRedemptionEnabled: value } })} />
                    <Check label="开放好友邀请奖励" checked={telegram.referralEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, referralEnabled: value } })} />
                    <Check label="开放匿名自愿排行榜" checked={telegram.leaderboardEnabled} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, leaderboardEnabled: value } })} />
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    <NumberInput label="每日基础积分" value={telegram.checkinBasePoints} min={1} max={10000} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, checkinBasePoints: value } })} />
                    <NumberInput label="连续奖励周期" value={telegram.checkinStreakBonusEvery} min={1} max={365} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, checkinStreakBonusEvery: value } })} />
                    <NumberInput label="周期额外积分" value={telegram.checkinStreakBonusPoints} min={0} max={10000} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, checkinStreakBonusPoints: value } })} />
                    <NumberInput label="兑换一天积分" value={telegram.pointsPerDay} min={1} max={1000000} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, pointsPerDay: value } })} />
                    <NumberInput label="单次最多兑换天数" value={telegram.maxRedeemDays} min={1} max={365} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, maxRedeemDays: value } })} />
                    <NumberInput label="邀请成功奖励" value={telegram.referralRewardPoints} min={0} max={1000000} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, referralRewardPoints: value } })} />
                    <NumberInput label="邀请有效天数" value={telegram.referralInviteValidDays} min={1} max={365} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, referralInviteValidDays: value } })} />
                    <NumberInput label="受邀账号天数" value={telegram.referralAccountDays} min={1} max={3650} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, referralAccountDays: value } })} />
                    <NumberInput label="每月邀请上限" value={telegram.referralMonthlyLimit} min={1} max={100} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, referralMonthlyLimit: value } })} />
                    <NumberInput label="排行榜人数" value={telegram.leaderboardLimit} min={3} max={50} onChange={(value) => setSettings({ ...settings, telegram: { ...telegram, leaderboardLimit: value } })} />
                  </div>
                </div>
              </Panel>
            </div>
          </Sheet>

          <Sheet className="rounded-[20px] p-6 sm:p-7">
            <SectionHeader eyebrow="公告" title="站点公告" body="控制首页和 Bot 公告中展示的内容。" />
            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              <Text label="标题" value={settings.announcement.title} onChange={(value) => setSettings({ ...settings, announcement: { ...settings.announcement, title: value } })} />
              <Text label="按钮文字" value={settings.announcement.linkLabel} onChange={(value) => setSettings({ ...settings, announcement: { ...settings.announcement, linkLabel: value } })} />
              <Textarea label="正文" compact value={settings.announcement.body} onChange={(value) => setSettings({ ...settings, announcement: { ...settings.announcement, body: value } })} />
              <UrlField label="跳转链接" optional value={settings.announcement.linkUrl} onChange={(value) => setSettings({ ...settings, announcement: { ...settings.announcement, linkUrl: value } })} />
            </div>
            <div className="mt-4"><Textarea label="时间线（时间|内容）" value={timelineText} onChange={setTimelineText} /></div>
          </Sheet>

          <Button variant="claret" className="w-full" loading={busy === 'save'} loadingText="保存中" disabled={!ready} onClick={saveSettings}>
            <Save size={16} /> 保存全部设置
          </Button>
        </div>}
      </div>
      {actionDialog && (
        <AdminActionDialog
          config={actionDialog}
          onClose={() => setActionDialog(null)}
        />
      )}
    </ShellBackdrop>
  );
}

function AdminActionDialog({ config, onClose }: { config: ActionDialogConfig; onClose: () => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(
    (config.fields || []).map((field) => [field.name, field.initial || '']),
  ));

  return (
    <AccessibleModal
      title={config.title}
      onClose={onClose}
      closeOnBackdrop={false}
      contentClassName="sheet w-full max-w-lg rounded-[20px] p-6 sm:p-7"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void config.onSubmit(values);
        }}
      >
        <h2 className="font-display text-2xl font-semibold">{config.title}</h2>
        <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{config.body}</p>
        {!!config.fields?.length && (
          <div className="mt-5 grid gap-4">
            {config.fields.map((field) => (
              <label key={field.name} className="block">
                <span className="text-sm font-semibold text-[var(--muted-foreground)]">{field.label}</span>
                {field.type === 'textarea' ? (
                  <textarea
                    className="field mt-2 min-h-24"
                    required={field.required}
                    value={values[field.name] || ''}
                    onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                  />
                ) : (
                  <input
                    className="field mt-2"
                    type={field.type || 'text'}
                    required={field.required}
                    min={field.min}
                    max={field.max}
                    value={values[field.name] || ''}
                    onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                  />
                )}
              </label>
            ))}
          </div>
        )}
        <div className="mt-6 grid gap-2 sm:grid-cols-2">
          <Button type="button" variant="secondary" onClick={onClose}>取消</Button>
          <Button type="submit" variant={config.danger ? 'danger' : 'claret'}>{config.confirmText}</Button>
        </div>
      </form>
    </AccessibleModal>
  );
}

function Text({ label, value, onChange, type = 'text', minLength, maxLength }: { label: string; value: string; onChange: (value: string) => void; type?: string; minLength?: number; maxLength?: number }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><input className="field mt-2" type={type} minLength={minLength} maxLength={maxLength} value={value || ''} onChange={(event) => onChange(event.target.value)} /></label>;
}

function Textarea({ label, value, onChange, compact = false }: { label: string; value: string; onChange: (value: string) => void; compact?: boolean }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><textarea className={`field mt-2 ${compact ? 'min-h-20' : 'min-h-28'}`} value={value || ''} onChange={(event) => onChange(event.target.value)} /></label>;
}

function UrlField({ label, value, onChange, optional = false }: { label: string; value: string; onChange: (value: string) => void; optional?: boolean }) {
  const href = /^https?:\/\//i.test(value.trim()) ? value.trim() : '';
  return (
    <label className="block">
      <span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}{optional ? '（可空）' : ''}</span>
      <div className="mt-2 flex gap-2">
        <input className="field min-w-0 flex-1" type="url" value={value || ''} onChange={(event) => onChange(event.target.value)} />
        {href && <a href={href} target="_blank" rel="noreferrer" className="btn btn-secondary !min-h-11 !px-3" aria-label={`打开${label}`}><ExternalLink size={15} /></a>}
      </div>
    </label>
  );
}

function NumberInput({ label, value, onChange, min = 0, max }: { label: string; value: number; onChange: (value: number) => void; min?: number; max?: number }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><input className="field mt-2" type="number" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4 border-b border-[rgba(231,246,253,.10)] py-2 text-sm font-semibold"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="size-5 accent-[var(--primary)]" /></label>;
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<[string, string]> }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><select className="field mt-2" value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>;
}

function StatCard({ label, value }: { label: string; value: number }) {
  return <div className="rounded-[14px] border border-[rgba(231,246,253,.14)] bg-[rgba(255,255,255,.06)] p-4"><p className="text-xs text-[var(--muted-foreground)]">{label}</p><p className="mt-1 font-display text-2xl font-semibold">{value}</p></div>;
}

function StatusPill({ user }: { user: AdminUser }) {
  const status = user.isExpired && user.status === 'active' ? 'expired' : user.status;
  const labels: Record<string, string> = { active: '正常', expired: '已到期', disabled: '已停用', deleted: '已删除', pending: '待启用' };
  const tone = status === 'active' ? 'tag-sage' : 'tag-claret';
  return <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${tone}`}>{labels[status] || status}</span>;
}

function SmallButton({ children, onClick, danger = false }: { children: ReactNode; onClick: () => void; danger?: boolean }) {
  return <button type="button" onClick={onClick} className={`inline-flex min-h-9 items-center gap-1.5 rounded-[10px] border px-3 py-1.5 text-xs font-semibold transition ${danger ? 'border-[rgba(239,68,68,.35)] text-red-300 hover:bg-[rgba(239,68,68,.10)]' : 'border-[rgba(231,246,253,.16)] hover:bg-[rgba(255,255,255,.08)]'}`}>{children}</button>;
}
