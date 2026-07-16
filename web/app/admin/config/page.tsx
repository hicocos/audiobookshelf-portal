'use client';

import { Activity, AlertTriangle, CalendarClock, Copy, ExternalLink, Eye, LayoutGrid, Lock, KeyRound, LogOut, Power, RefreshCcw, Save, Search, Settings, ShieldCheck, Trash2, UserCog, UserPlus, Users, X } from 'lucide-react';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { Button, LoadingScreen, Panel, PromptModal, SectionHeader, Sheet, ShellBackdrop, StatusNote, WordMark } from '@/components/ui';
import { api, clearSession, AdminLibraryOverview, AdminUser, CodeRecord, PublicSettings } from '@/lib/api';

const codeTypeLabels: Record<string, string> = { register: '注册邀请码', renew: '续期码' };
const statusLabels: Record<string, string> = { active: '正常', expired: '已到期', disabled: '已停用', deleted: '需处理', pending: '待启用' };
const defaultSettings: PublicSettings = {
  siteName: 'MoYin.CC', tagline: '安静的声音栖地', registrationEnabled: true, passwordMinLength: 3,
  copy: { heroKicker: 'AUDIO ISLAND', heroTitle: 'MoYin.CC', heroSubtitle: '安静的声音栖地', primaryCta: '申请访问', secondaryCta: '进入账号中心', notice: '一处安静、专注的声音栖地。' },
  links: { libraryUrl: '', supportUrl: '', announcementUrl: '' },
  client: { serverUrl: 'https://listen.moyin.cc', androidDownloadUrl: 'https://mikupan.com/s/AOrU0', iosGuideText: '在 App Store 搜索“EchoShelf”并安装。', desktopGuideText: '暂无稳定方案，建议使用手机或平板。' },
  announcement: { title: '', body: '', linkUrl: '', linkLabel: '', timeline: [] },
  features: { registration: true, showLibraryEntry: false, showSupportEntry: false, showAnnouncements: true },
  operations: { inactivityAutoDisable: false, inactiveDays: 30, newUserGraceDays: 7, lastInactivityCheckAt: null, lastInactivityDisabled: 0 },
  sections: { benefits: [], steps: [], faq: [] },
};
type AdminTab = 'overview' | 'codes' | 'accounts' | 'users' | 'settings';

export default function AdminConfigPage() {
  const [tab, setTab] = useState<AdminTab>('overview');
  const [durationDays, setDurationDays] = useState(30);
  const [permanent, setPermanent] = useState(false);
  const [count, setCount] = useState(5);
  const [maxUses, setMaxUses] = useState(1);
  const [type, setType] = useState('register');
  const [codes, setCodes] = useState<CodeRecord[]>([]);
  const [codePages, setCodePages] = useState<Record<string, number>>({ register: 1, renew: 1 });
  const [activeCodeType, setActiveCodeType] = useState('register');
  const [codeDeleteTarget, setCodeDeleteTarget] = useState<CodeRecord | null>(null);
  const [settings, setSettings] = useState<PublicSettings>(defaultSettings);
  const [bulkPreview, setBulkPreview] = useState<Awaited<ReturnType<typeof api.adminBulkExtendUserExpiryPreview>>['summary'] | null>(null);
  const [overview, setOverview] = useState<AdminLibraryOverview | null>(null);
  const [prompt, setPrompt] = useState<{ title: string; body: ReactNode } | null>(null);
  const [stepsText, setStepsText] = useState(defaultSettings.sections.steps.join('\n'));
  const [faqText, setFaqText] = useState('');
  const [timelineText, setTimelineText] = useState('');
  const [userQuery, setUserQuery] = useState('');
  const [message, setMessage] = useState('正在验证管理员登录状态…');
  const [settingsReady, setSettingsReady] = useState(false);
  const [busy, setBusy] = useState('');

  // --- account management (real CRUD via portal, replaces ABS backend) ---
  const [accounts, setAccounts] = useState<AdminUser[]>([]);
  const [accountStats, setAccountStats] = useState({ total: 0, active: 0, disabled: 0, expired: 0 });
  const [upstreamAvailable, setUpstreamAvailable] = useState(true);
  const [accountQuery, setAccountQuery] = useState('');
  const [newUser, setNewUser] = useState({ username: '', password: '', durationDays: 30 });
  const [confirm, setConfirm] = useState<{ kind: 'delete' | 'disable' | 'enable'; user: AdminUser } | null>(null);
  const [pwTarget, setPwTarget] = useState<AdminUser | null>(null);
  const [pwValue, setPwValue] = useState('');
  const [expiryTarget, setExpiryTarget] = useState<AdminUser | null>(null);
  const [bulkExpiryOpen, setBulkExpiryOpen] = useState(false);
  const [bulkExtendDays, setBulkExtendDays] = useState(7);
  const [bulkReason, setBulkReason] = useState('服务器波动补偿');


  const riskyUsers = useMemo(() => (overview?.users || []).filter((u) => u.inactivityCandidate), [overview]);
  const filteredUsers = useMemo(() => {
    const q = userQuery.trim().toLowerCase();
    const users = overview?.users || [];
    if (!q) return users;
    return users.filter((u) => `${u.username} ${u.portalStatus || ''} ${u.inactivityReason || ''}`.toLowerCase().includes(q));
  }, [overview?.users, userQuery]);

  async function loadCodes() { setCodes((await api.listCodes()).codes); }
  function hydrateSettingsForm(value: PublicSettings) {
    const merged = {
      ...defaultSettings,
      ...value,
      copy: { ...defaultSettings.copy, ...(value.copy || {}) },
      links: { ...defaultSettings.links, ...(value.links || {}) },
      client: { ...defaultSettings.client, ...(value.client || {}) },
      announcement: { ...defaultSettings.announcement, ...(value.announcement || {}) },
      features: { ...defaultSettings.features, ...(value.features || {}) },
      operations: { ...defaultSettings.operations, ...(value.operations || {}) },
      sections: { ...defaultSettings.sections, ...(value.sections || {}) },
    };
    setSettings(merged);
    setStepsText((merged.sections.steps || []).join('\n'));
    setFaqText((merged.sections.faq || []).map((item) => `${item.q}|${item.a}`).join('\n'));
    setTimelineText((merged.announcement.timeline || []).map((it) => `${it.date || ''}|${it.body || ''}`).join('\n'));
  }
  async function loadSettings() {
    setSettingsReady(false);
    try {
      const r = await api.getPublicSettings();
      hydrateSettingsForm(r.settings);
      setSettingsReady(true);
    } catch {
      try {
        const fallback = await api.config();
        hydrateSettingsForm(fallback);
      } catch {
        // Keep defaults visible, but never permit saving an unverified form.
      }
    }
  }
  async function refreshOverview() { setOverview(await api.adminLibraryOverview()); }
  async function refreshAccounts() {
    const r = await api.adminListUsers();
    setAccounts(r.users); setAccountStats(r.stats); setUpstreamAvailable(r.upstreamAvailable);
  }

  const filteredAccounts = useMemo(() => {
    const q = accountQuery.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter((u) => `${u.username} ${u.status} ${u.email || ''}`.toLowerCase().includes(q));
  }, [accounts, accountQuery]);

  useEffect(() => {
    let cancelled = false;
    async function initAdmin() {
      setMessage('正在加载管理台数据…');
      const session = await api.sessionStatus().catch(() => ({ authenticated: false, admin: false }));
      if (cancelled) return;
      if (!session.authenticated || !session.admin) {
        setMessage('请先登录管理员账号，正在跳转登录页…');
        setTimeout(() => { location.href = '/admin'; }, 800);
        return;
      }
      const tasks = await Promise.allSettled([loadCodes(), loadSettings(), refreshOverview(), refreshAccounts()]);
      if (cancelled) return;
      const failed = tasks.filter((item) => item.status === 'rejected').length;
      setMessage(failed ? `管理台已打开，但有 ${failed} 个模块暂时加载失败；可切换到对应页面后刷新。` : '');
    }
    void initAdmin();
    return () => { cancelled = true; };
  }, []);


  useEffect(() => {
    const scrollTarget = document.querySelector('main');
    scrollTarget?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [tab]);

  useEffect(() => {
    if (!message || message.includes('正在') || message.includes('请先')) return;
    const timer = window.setTimeout(() => setMessage(''), 2800);
    return () => window.clearTimeout(timer);
  }, [message]);

  // --- account mutations ---
  async function createAccount() {
    if (!newUser.username.trim() || !newUser.password.trim()) { setMessage('请填写用户名和密码'); return; }
    if (newUser.password.length < settings.passwordMinLength) { setMessage(`密码至少需要 ${settings.passwordMinLength} 位。`); return; }
    if (newUser.durationDays < 0 || newUser.durationDays > 3650) { setMessage('有效天数必须在 0 到 3650 之间。'); return; }
    const usernameToCreate = newUser.username.trim();
    const initialPassword = newUser.password;
    const durationDays = newUser.durationDays;
    setMessage(''); setBusy('createUser');
    try {
      await api.adminCreateUser({ username: usernameToCreate, password: initialPassword, durationDays });
      setNewUser({ username: '', password: '', durationDays: 30 });
      await refreshAccounts();
      setPrompt({
        title: '账号已创建',
        body: <DeliveryCard username={usernameToCreate} password={initialPassword} serverUrl={settings.client.serverUrl || 'https://listen.moyin.cc'} />,
      });
    } catch (err) { setMessage(err instanceof Error ? err.message : '创建失败'); }
    finally { setBusy(''); }
  }
  async function submitPassword() {
    if (!pwTarget || !pwValue.trim()) return;
    if (pwValue.length < settings.passwordMinLength) { setMessage(`密码至少需要 ${settings.passwordMinLength} 位。`); return; }
    setBusy('pw');
    try { await api.adminSetUserPassword(pwTarget.id, pwValue); setMessage(`已重置 ${pwTarget.username} 的密码`); setPwTarget(null); setPwValue(''); await refreshAccounts(); }
    catch (err) { setMessage(err instanceof Error ? err.message : '改密失败'); }
    finally { setBusy(''); }
  }
  async function submitExpiry(payload: { extendDays?: number; clear?: boolean; expiresAt?: string }) {
    if (!expiryTarget) return;
    setBusy('expiry');
    try { await api.adminSetUserExpiry(expiryTarget.id, payload); setMessage(`已更新 ${expiryTarget.username} 的有效期`); setExpiryTarget(null); await refreshAccounts(); }
    catch (err) { setMessage(err instanceof Error ? err.message : '更新有效期失败'); }
    finally { setBusy(''); }
  }
  async function openBulkExpiryPreview() {
    const days = Math.trunc(Number(bulkExtendDays) || 0);
    if (days <= 0) { setMessage('批量补偿天数必须大于 0'); return; }
    setBulkExpiryOpen(true);
    setBulkPreview(null);
    try {
      const r = await api.adminBulkExtendUserExpiryPreview({ extendDays: days });
      setBulkPreview(r.summary);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '批量预览失败');
    }
  }
  async function submitBulkExpiry() {
    const days = Math.trunc(Number(bulkExtendDays) || 0);
    if (days <= 0) { setMessage('批量补偿天数必须大于 0'); return; }
    setBusy('bulkExpiry');
    try {
      const r = await api.adminBulkExtendUserExpiry({ extendDays: days, reason: bulkReason.trim() || undefined });
      setMessage(`批量操作完成：已为 ${r.summary.updated} 个普通用户增加 ${days} 天有效期，恢复 ${r.summary.reactivated} 个到期账号，跳过 ${r.summary.skippedAdmins} 个管理员。`);
      setBulkExpiryOpen(false);
      await refreshAccounts();
    } catch (err) { setMessage(err instanceof Error ? err.message : '批量操作失败'); }
    finally { setBusy(''); }
  }
  async function runConfirm() {
    if (!confirm) return;
    const { kind, user } = confirm; setBusy('confirm');
    try {
      if (kind === 'delete') { await api.adminDeleteUser(user.id); setMessage(`已删除账号 ${user.username}`); }
      else { await api.adminSetUserStatus(user.id, kind); setMessage(`已${kind === 'enable' ? '启用' : '停用'} ${user.username}`); }
      setConfirm(null); await refreshAccounts();
    } catch (err) { setMessage(err instanceof Error ? err.message : '操作失败'); }
    finally { setBusy(''); }
  }


  async function createCodes() {
    const safeCount = Math.max(1, Math.min(100, Math.trunc(Number(count) || 1)));
    const safeMaxUses = Math.max(1, Math.min(10000, Math.trunc(Number(maxUses) || 1)));
    const safeDurationDays = permanent ? 0 : Math.max(1, Math.min(3650, Math.trunc(Number(durationDays) || 1)));
    setMessage(''); setBusy('codes');
    try {
      const r = await api.createCodes({ type, durationDays: safeDurationDays, count: safeCount, maxUses: safeMaxUses, note: permanent ? '永久卡密' : safeMaxUses > 1 ? `可用 ${safeMaxUses} 次` : 'admin generated' });
      setCodes([...r.codes, ...codes]); setCodePages({ register: 1, renew: 1 }); setMessage(`生成 ${r.codes.length} 个${permanent ? '永久' : ''}卡密${safeMaxUses > 1 ? `，每个可用 ${safeMaxUses} 次` : ''}`);
    } catch (err) { setMessage(err instanceof Error ? err.message : '生成失败，请先登录管理员账号'); }
    finally { setBusy(''); }
  }
  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setPrompt({ title: '卡密已复制', body: <>已复制卡密 <code>{code}</code>，可以直接粘贴发送给用户。</> });
    } catch {
      setPrompt({ title: '复制失败', body: <>浏览器没有允许自动复制，请长按卡密 <code>{code}</code> 手动复制。</> });
    }
  }
  async function toggleCodeStatus(code: CodeRecord) {
    setMessage(''); setBusy(`code-${code.id}`);
    try {
      const next = code.status === 'disabled' ? 'active' : 'disabled';
      const r = await api.updateCodeStatus(code.id, next);
      setCodes(codes.map((item) => item.id === code.id ? r.code : item));
      setMessage(`${next === 'disabled' ? '已禁用' : '已启用'}卡密 ${code.code}`);
    } catch (err) { setMessage(err instanceof Error ? err.message : '卡密状态更新失败'); }
    finally { setBusy(''); }
  }
  async function deleteCode() {
    if (!codeDeleteTarget) return;
    setBusy(`delete-code-${codeDeleteTarget.id}`);
    try {
      await api.deleteCode(codeDeleteTarget.id);
      setCodes(codes.filter((item) => item.id !== codeDeleteTarget.id));
      setMessage(`已删除卡密 ${codeDeleteTarget.code}`);
      setCodeDeleteTarget(null);
    } catch (err) { setMessage(err instanceof Error ? err.message : '删除卡密失败'); }
    finally { setBusy(''); }
  }
  async function saveSettings() {
    if (!settingsReady) {
      setMessage('管理配置未完整加载，已禁止保存以避免覆盖现有内容。请刷新后重试。');
      return;
    }
    setMessage(''); setBusy('settings');
    const faq = faqText.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => { const [q, ...rest] = line.split('|'); return { q: q.trim(), a: rest.join('|').trim() }; }).filter((item) => item.q && item.a);
    const timeline = timelineText.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => { const [date, ...rest] = line.split('|'); return { date: date.trim(), body: rest.join('|').trim() }; }).filter((item) => item.body);
    const payload: Partial<PublicSettings> = {
      ...settings,
      copy: { ...settings.copy, notice: settings.copy.notice.trim() || '一处安静、专注的声音栖地。' },
      client: {
        ...settings.client,
        iosGuideText: settings.client.iosGuideText.trim() || '在 App Store 搜索“EchoShelf”并安装。',
        desktopGuideText: settings.client.desktopGuideText.trim() || '暂无稳定方案，建议使用手机或平板。',
      },
      announcement: { ...settings.announcement, timeline },
      sections: { ...settings.sections, steps: stepsText.split('\n').map((s) => s.trim()).filter(Boolean), faq },
      features: { ...settings.features, showLibraryEntry: false },
      links: { ...settings.links, libraryUrl: '' },
    };
    try { const r = await api.updatePublicSettings(payload); setSettings({ ...defaultSettings, ...r.settings, operations: { ...defaultSettings.operations, ...(r.settings.operations || {}) } }); setMessage('设置已保存'); await refreshOverview(); }
    catch (err) { setMessage(err instanceof Error ? err.message : '保存失败，请确认管理员登录状态'); }
    finally { setBusy(''); }
  }
  async function runInactivityCheck() {
    setMessage('正在执行活跃度巡检…'); setBusy('inactivity');
    try { const r = await api.runInactivityCheck(); setSettings({ ...defaultSettings, ...r.settings, operations: { ...defaultSettings.operations, ...(r.settings.operations || {}) } }); setMessage(`巡检完成：检查 ${r.result.checked} 个账号，处理 ${r.result.disabled} 个账号`); await refreshOverview(); }
    catch (err) { setMessage(err instanceof Error ? err.message : '巡检失败'); }
    finally { setBusy(''); }
  }
  async function logout() { setBusy('logout'); try { await clearSession(); } finally { location.href = '/admin'; } }

  const noteTone = message.includes('失败') || message.includes('请先') ? 'warning' : message.includes('保存') || message.includes('生成') || message.includes('完成') || message.includes('复制') || message.includes('删除') || message.includes('禁用') || message.includes('启用') ? 'success' : 'neutral';
  const codeGroups = [
    { type: 'register', label: '注册邀请码', body: '新用户注册开通' },
    { type: 'renew', label: '续期码', body: '已有账号延长有效期' },
  ].map((group) => {
    const all = codes.filter((code) => code.type === group.type);
    const pageSize = 10;
    const totalPages = Math.max(1, Math.ceil(all.length / pageSize));
    const page = Math.min(codePages[group.type] || 1, totalPages);
    const visible = all.slice((page - 1) * pageSize, page * pageSize);
    return { ...group, all, visible, page, totalPages };
  });
  const activeCodeGroup = codeGroups.find((group) => group.type === activeCodeType) || codeGroups[0];

  return (
    <ShellBackdrop className="w-full px-3 pb-40 pt-5 sm:px-6 sm:pt-7 lg:pb-8">
      {busy === 'logout' && <LoadingScreen title="正在退出" subtitle="console" />}
      <div className="app-content w-full">
        {/* header — only on overview; compact brand + logout + stats */}
        {tab === 'overview' && (
          <header className="admin-overview-hero sheet rounded-[20px] p-5 sm:p-6">
            <div className="flex flex-row items-center justify-between gap-3">
              <WordMark siteName={settings.siteName} tagline="管理台" small />
              <Button variant="secondary" className="shrink-0" loading={busy === 'logout'} loadingText="退出中" onClick={logout}><LogOut size={15} /> 退出登录</Button>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              <DarkStatLight label="门户用户" value={`${overview?.stats.portalUserCount ?? 0} 个`} />
              <DarkStatLight label="启用账号" value={`${overview?.stats.activeUserCount ?? 0} 个`} />
              <DarkStatLight label="待关注" value={`${overview?.stats.inactiveCandidateCount ?? 0} 个`} />
            </div>
          </header>
        )}
        {message && <div className={tab === 'overview' ? 'mt-4' : 'mt-0'}><StatusNote tone={noteTone}>{message}</StatusNote></div>}

        {/* OVERVIEW */}
        {tab === 'overview' && (
          <div className="mt-5 grid gap-5">
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <SectionHeader eyebrow="运营概览" title="运营驾驶舱" body="集中查看用户规模、近期收听情况和自动巡检结果。" />
              <Panel className="mt-6 rounded-[16px] p-5">
                <div className="flex items-center gap-2 font-display font-semibold"><Activity size={18} /> 运营建议</div>
                <ul className="mt-3 space-y-2 text-sm leading-6 text-[var(--muted-foreground)]">
                  <li>· 在「用户」页按用户名或状态搜索，优先处理待关注账号。</li>
                  <li>· 在「配置」页维护首页文案、客户端步骤与客服入口，减少重复沟通。</li>
                  <li>· 巡检策略只处理符合条件的账号，续期后可恢复。</li>
                </ul>
              </Panel>
            </Sheet>
          </div>
        )}

        {/* CODES */}
        {tab === 'codes' && (
          <Sheet className="rounded-[20px] p-6 sm:p-7">
            <SectionHeader eyebrow="卡密管理" title="生成邀请码 / 续期码" body="永久卡密可将账号设为长期有效；普通卡密会按照设定天数延长有效期。" />
            <div className="mt-6 grid gap-4 sm:grid-cols-5">
              <Select label="卡密类型" value={type} onChange={setType} options={[['register', '注册邀请码'], ['renew', '续期码']]} hint={`当前：${codeTypeLabels[type]}`} />
              <NumberInput label="有效天数" value={durationDays} min={1} disabled={permanent} onChange={setDurationDays} hint="永久卡密无需天数" />
              <NumberInput label="生成数量" value={count} min={1} max={100} onChange={setCount} hint="一次生成几张卡密" />
              <NumberInput label="每张可用次数" value={maxUses} min={1} max={10000} onChange={setMaxUses} hint="支持多人共用同一张卡密" />
              <CheckPanel label="永久卡密" checked={permanent} onChange={setPermanent} />
            </div>
            <Button variant="claret" className="mt-5 w-full sm:w-auto" loading={busy === 'codes'} loadingText="生成中" onClick={createCodes}><KeyRound size={16} /> 生成卡密</Button>
            <div className="mt-8 flex items-center justify-between gap-3">
              <h3 className="display-md text-[1.4rem]">卡密列表</h3>
              <p className="text-sm text-[var(--muted-foreground)]">共 {codes.length} 个，按类型归类</p>
            </div>
            <Panel className="mt-4 rounded-[16px] p-3 sm:p-4">
              <div className={`grid gap-1 rounded-[14px] border border-[rgba(231,246,253,.12)] bg-[rgba(255,255,255,.08)] p-1 ${codeGroups.length === 2 ? 'grid-cols-2' : 'grid-cols-3'}`}>
                {codeGroups.map((group) => (
                  <button key={group.type} onClick={() => setActiveCodeType(group.type)} className={`min-w-0 rounded-[11px] px-2 py-2 text-left transition ${activeCodeType === group.type ? 'border border-[rgba(0,190,227,.58)] bg-[rgba(0,190,227,.18)] text-[var(--foreground)] shadow-sm' : 'text-[var(--foreground)] hover:bg-[rgba(255,255,255,.08)]'}`}>
                    <span className="block truncate font-display text-[13px] font-semibold leading-5 sm:text-base">{group.label}</span>
                    <span className={`mt-0.5 block truncate text-[10px] leading-4 sm:text-xs ${activeCodeType === group.type ? 'text-[var(--muted-foreground)]' : 'text-[var(--muted-foreground)]'}`}>{group.all.length} 个 · {group.body}</span>
                  </button>
                ))}
              </div>

              <div className="mt-4 flex items-center justify-between gap-3 border-b border-[rgba(231,246,253,.12)] pb-3">
                <div className="min-w-0">
                  <h4 className="font-display text-lg font-semibold">{activeCodeGroup.label}</h4>
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">每页 10 个，点上方分类切换，不刷新页面。</p>
                </div>
                <span className="chip shrink-0">{activeCodeGroup.all.length} 个</span>
              </div>

              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {activeCodeGroup.visible.map((c) => (
                  <div key={c.id} className="rounded-[12px] border border-[rgba(231,246,253,.22)] bg-[rgba(255,255,255,.09)] p-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="min-w-0 flex-1 truncate font-mono text-sm font-semibold" title={c.code}>{c.code}</p>
                      <button title="复制" className="inline-flex min-h-8 shrink-0 items-center gap-1 rounded-lg border border-[rgba(231,246,253,.16)] bg-[rgba(255,255,255,.08)] px-2 text-xs font-semibold text-[var(--foreground)]" onClick={() => copyCode(c.code)}><Copy size={13} /> 复制</button>
                    </div>
                    <p className="mt-1 truncate text-xs text-[var(--muted-foreground)]">{c.durationDays === 0 ? '永久' : `${c.durationDays} 天`} · 已用 {c.usedCount}/{c.maxUses} · {c.status === 'disabled' ? '已禁用' : c.usedCount >= c.maxUses ? '已用完' : '可用'}</p>
                    <div className="mt-3 grid grid-cols-2 gap-2">
                      <button className="inline-flex min-h-8 items-center justify-center gap-1 rounded-lg border border-[rgba(231,246,253,.16)] bg-[rgba(255,255,255,.08)] px-2 text-xs font-semibold text-[var(--foreground)] disabled:opacity-40" disabled={busy === `code-${c.id}` || (c.status === 'disabled' && c.usedCount >= c.maxUses)} onClick={() => toggleCodeStatus(c)}><Power size={13} />{c.status === 'disabled' ? '启用' : '禁用'}</button>
                      <button className="inline-flex min-h-8 items-center justify-center gap-1 rounded-lg border border-[rgba(0,190,227,.32)] bg-[rgba(255,255,255,.08)] px-2 text-xs font-semibold text-[var(--primary)] disabled:opacity-40" disabled={busy === `delete-code-${c.id}`} onClick={() => setCodeDeleteTarget(c)}><Trash2 size={13} />删除</button>
                    </div>
                  </div>
                ))}
              </div>

              {!activeCodeGroup.all.length && <p className="mt-4 rounded-[12px] border border-dashed border-[rgba(231,246,253,.16)] bg-[rgba(255,255,255,.08)] p-5 text-center text-sm text-[var(--muted-foreground)]">暂无{activeCodeGroup.label}</p>}
              {activeCodeGroup.totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between gap-3 border-t border-[rgba(231,246,253,.12)] pt-3">
                  <button className="btn btn-secondary !min-h-9 !rounded-lg !px-3 !py-1.5 text-xs" disabled={activeCodeGroup.page <= 1} onClick={() => setCodePages({ ...codePages, [activeCodeGroup.type]: activeCodeGroup.page - 1 })}>上一页</button>
                  <span className="text-xs font-semibold text-[var(--muted-foreground)]">{activeCodeGroup.page} / {activeCodeGroup.totalPages}</span>
                  <button className="btn btn-secondary !min-h-9 !rounded-lg !px-3 !py-1.5 text-xs" disabled={activeCodeGroup.page >= activeCodeGroup.totalPages} onClick={() => setCodePages({ ...codePages, [activeCodeGroup.type]: activeCodeGroup.page + 1 })}>下一页</button>
                </div>
              )}
            </Panel>
            {!codes.length && <p className="mt-4 text-[var(--muted-foreground)]">暂无卡密。</p>}
          </Sheet>
        )}

        {/* ACCOUNTS — real user management, replaces ABS backend */}
        {tab === 'accounts' && (
          <div className="grid gap-5">
            <Sheet className="rounded-[20px] p-6 sm:p-7">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <SectionHeader eyebrow="用户账号" title="账号管理" body="可直接创建账号、重置密码、启用或停用账号，以及调整有效期，无需进入媒体后台。" />
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={openBulkExpiryPreview}><CalendarClock size={15} /> 批量补偿有效期</Button>
                  <Button variant="secondary" onClick={async () => { setBusy('refreshAcc'); await refreshAccounts().finally(() => setBusy('')); }} loading={busy === 'refreshAcc'} loadingText="刷新中"><RefreshCcw size={15} /> 刷新</Button>
                </div>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-4">
                <DarkStatLight label="账号总数" value={`${accountStats.total}`} />
                <DarkStatLight label="启用中" value={`${accountStats.active}`} />
                <DarkStatLight label="已停用" value={`${accountStats.disabled}`} />
                <DarkStatLight label="已到期" value={`${accountStats.expired}`} />
              </div>
              {!upstreamAvailable && <div className="mt-4"><StatusNote tone="warning"><AlertTriangle size={16} className="mr-1 inline" /> 暂时无法连接媒体服务器，启用状态可能不是最新；改密/启停操作会失败，请稍后重试。</StatusNote></div>}

              <Panel className="mt-6 rounded-[16px] p-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2 font-display font-semibold"><CalendarClock size={18} /> 批量有效期补偿</div>
                    <p className="mt-1 text-xs leading-5 text-[rgba(166,191,202,.72)]">用于服务器波动等场景：一键给所有普通用户增加有效期，管理员账号会自动跳过。</p>
                  </div>
                  <Button variant="claret" onClick={openBulkExpiryPreview}><CalendarClock size={15} /> 给所有用户 +{bulkExtendDays || 7} 天</Button>
                </div>
              </Panel>

              <Panel className="mt-6 rounded-[16px] p-5">
                <div className="flex items-center gap-2 font-display font-semibold"><UserPlus size={18} /> 新建账号</div>
                <div className="mt-4 grid gap-3 sm:grid-cols-[1.2fr_1.2fr_.8fr_auto] sm:items-end">
                  <Field label="用户名"><input className="field" placeholder="英文/数字/_.-" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} /></Field>
                  <Field label="初始密码"><input className="field" type="password" placeholder="至少符合密码长度" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} /></Field>
                  <Field label="有效天数"><input className="field" type="number" min={0} value={newUser.durationDays} onChange={(e) => setNewUser({ ...newUser, durationDays: Math.max(0, Number(e.target.value) || 0) })} /></Field>
                  <Button variant="claret" loading={busy === 'createUser'} loadingText="创建中" onClick={createAccount}><UserPlus size={15} /> 创建</Button>
                </div>
                <p className="mt-2 text-xs text-[rgba(166,191,202,.72)]">有效天数填 0 表示长期有效。账号会同步在媒体服务器创建。</p>
              </Panel>

              <label className="relative mt-6 block">
                <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]" size={16} />
                <input className="field !pl-10" placeholder="搜索用户名 / 状态 / 邮箱" value={accountQuery} onChange={(e) => setAccountQuery(e.target.value)} />
              </label>

              <div className="admin-scroll-list mt-4 grid gap-3">
                {filteredAccounts.map((u) => (
                  <Panel key={u.id} className="rounded-[16px] p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-display font-semibold">{u.username}</p>
                          <StatusBadge status={u.status} isExpired={u.isExpired} />
                          {u.upstreamFound === false && <span className="rounded-full bg-[rgba(0,190,227,.12)] px-2 py-0.5 text-[11px] font-semibold text-[var(--primary)]">媒体端缺失</span>}
                        </div>
                        <p className="mt-1 text-xs text-[var(--muted-foreground)]">{u.email || '无邮箱'} · 有效期：{u.expiresAt ? new Date(u.expiresAt).toLocaleString('zh-CN') : '长期'} · 创建：{u.createdAt ? new Date(u.createdAt).toLocaleDateString('zh-CN') : '-'}</p>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <MiniBtn onClick={() => { setPwTarget(u); setPwValue(''); }}><Lock size={13} /> 改密</MiniBtn>
                      <MiniBtn onClick={() => setExpiryTarget(u)}><CalendarClock size={13} /> 有效期</MiniBtn>
                      {u.status === 'disabled'
                        ? <MiniBtn onClick={() => setConfirm({ kind: 'enable', user: u })}><Power size={13} /> 启用</MiniBtn>
                        : <MiniBtn onClick={() => setConfirm({ kind: 'disable', user: u })}><Power size={13} /> 停用</MiniBtn>}
                      <MiniBtn danger onClick={() => setConfirm({ kind: 'delete', user: u })}><Trash2 size={13} /> 删除</MiniBtn>
                    </div>
                  </Panel>
                ))}
                {!filteredAccounts.length && <p className="text-[var(--muted-foreground)]">没有匹配的账号。</p>}
              </div>
            </Sheet>
          </div>
        )}


        {/* USERS */}
        {tab === 'users' && (
          <Sheet className="rounded-[20px] p-6 sm:p-7">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <SectionHeader eyebrow="用户状态" title="用户与活跃度" body="结合账号状态、最近收听记录和巡检策略，快速找到需要关注的用户。" />
              <Button variant="secondary" onClick={async () => { setBusy('refresh'); await refreshOverview().finally(() => setBusy('')); }} loading={busy === 'refresh'} loadingText="刷新中"><RefreshCcw size={15} /> 刷新</Button>
            </div>
            <div className="mt-5 grid gap-3 lg:grid-cols-[1fr_auto]">
              <label className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]" size={16} />
                <input className="field !pl-10" placeholder="搜索用户名、状态或判断原因" value={userQuery} onChange={(e) => setUserQuery(e.target.value)} />
              </label>
              <span className="chip"><Eye size={14} /> 当前显示 {filteredUsers.length} 个</span>
            </div>
            <div className="mt-5"><StatusNote tone="warning"><AlertTriangle size={16} className="mr-1 inline" /> 新用户默认 {settings.operations.newUserGraceDays} 天宽限期；超过宽限且 {settings.operations.inactiveDays} 天无记录时进入待关注。</StatusNote></div>
            {riskyUsers.length > 0 && <div className="mt-4"><StatusNote tone="danger">当前有 {riskyUsers.length} 个用户被策略标记为待关注。</StatusNote></div>}
            <div className="admin-scroll-list mt-5 grid gap-3">
              {filteredUsers.map((user) => (
                <Panel key={user.id} className="rounded-[16px] p-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="font-display font-semibold">{user.username}</p>
                      <p className="mt-1 text-xs text-[var(--muted-foreground)]">门户状态：{user.portalStatus ? statusLabels[user.portalStatus] || user.portalStatus : '未绑定'} · 启用：{user.isActive ? '是' : '否'} · 记录 {user.progressCount} 条</p>
                    </div>
                    <span className={`w-fit rounded-full px-3 py-1 text-xs font-semibold ${user.inactivityCandidate ? 'tag-claret' : 'tag-sage'}`}>{user.inactivityCandidate ? '待关注' : '正常'}</span>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-[var(--muted-foreground)] sm:grid-cols-3">
                    <p>最近登录：{user.lastSeen ? new Date(user.lastSeen).toLocaleString('zh-CN') : '未知'}</p>
                    <p>最近收听：{user.latestListenAt ? new Date(user.latestListenAt).toLocaleString('zh-CN') : '暂无'}</p>
                    <p>判断：{user.inactivityReason || '-'}</p>
                  </div>
                </Panel>
              ))}
            </div>
          </Sheet>
        )}

        {/* SETTINGS */}
        {tab === 'settings' && (
          <Sheet className="rounded-[20px] p-6 sm:p-7">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <SectionHeader eyebrow="系统设置" title="配置" body="修改前台内容、客户端下载和运营规则。" />
              <Button variant="claret" loading={busy === 'settings'} loadingText="保存中" disabled={!settingsReady} onClick={saveSettings}><Save size={16} /> 保存设置</Button>
            </div>
            <div className="mt-6 grid gap-5">
              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">前台展示</h3>
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <Text label="品牌名称" value={settings.siteName} onChange={(v) => setSettings({ ...settings, siteName: v })} />
                  <Text label="页头短句" value={settings.tagline} onChange={(v) => setSettings({ ...settings, tagline: v })} />
                  <Text label="首页标签" value={settings.copy.heroKicker} onChange={(v) => setSettings({ ...settings, copy: { ...settings.copy, heroKicker: v } })} />
                  <Text label="主按钮" value={settings.copy.primaryCta} onChange={(v) => setSettings({ ...settings, copy: { ...settings.copy, primaryCta: v } })} />
                  <Textarea compact label="首页主标题" value={settings.copy.heroTitle} onChange={(v) => setSettings({ ...settings, copy: { ...settings.copy, heroTitle: v } })} />
                  <Textarea compact label="首页副标题" value={settings.copy.heroSubtitle} onChange={(v) => setSettings({ ...settings, copy: { ...settings.copy, heroSubtitle: v } })} />
                  <Textarea compact label="首页简介" value={settings.copy.notice} onChange={(v) => setSettings({ ...settings, copy: { ...settings.copy, notice: v } })} />
                  <UrlField label="客服链接" value={settings.links.supportUrl} onChange={(v) => setSettings({ ...settings, links: { ...settings.links, supportUrl: v } })} optional />
                </div>
              </Panel>

              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">客户端与下载</h3>
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <UrlField label="听书服务器地址" value={settings.client.serverUrl} onChange={(v) => setSettings({ ...settings, client: { ...settings.client, serverUrl: v } })} />
                  <UrlField label="Android 安装包" value={settings.client.androidDownloadUrl} onChange={(v) => setSettings({ ...settings, client: { ...settings.client, androidDownloadUrl: v } })} optional />
                  <Textarea compact label="iPhone / iPad 安装说明" value={settings.client.iosGuideText} onChange={(v) => setSettings({ ...settings, client: { ...settings.client, iosGuideText: v } })} />
                  <Textarea compact label="电脑端使用说明" value={settings.client.desktopGuideText} onChange={(v) => setSettings({ ...settings, client: { ...settings.client, desktopGuideText: v } })} />
                </div>
              </Panel>

              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">页面内容</h3>
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <Textarea label="开始步骤（每行一条）" value={stepsText} onChange={setStepsText} />
                  <Textarea label="常见问题（问题|答案）" value={faqText} onChange={setFaqText} />
                </div>
              </Panel>

              <Panel className="rounded-[16px] p-5">
                <p className="mb-3 text-sm font-semibold text-[var(--muted-foreground)]">功能开关</p>
                <Check label="开放注册" checked={settings.features.registration} onChange={(v) => setSettings({ ...settings, features: { ...settings.features, registration: v } })} />
                <Check label="显示客服入口" checked={settings.features.showSupportEntry} onChange={(v) => setSettings({ ...settings, features: { ...settings.features, showSupportEntry: v } })} />
                <Check label="显示公告入口" checked={settings.features.showAnnouncements} onChange={(v) => setSettings({ ...settings, features: { ...settings.features, showAnnouncements: v } })} />
              </Panel>
              <Panel className="rounded-[16px] p-5 lg:col-span-2">
                <h3 className="font-display text-lg font-semibold">公告</h3>
                <div className="grid gap-4 lg:grid-cols-2">
                  <Text label="标题" value={settings.announcement?.title || ''} onChange={(v) => setSettings({ ...settings, announcement: { ...settings.announcement, title: v } })} />
                  <Text label="按钮文字" value={settings.announcement?.linkLabel || ''} onChange={(v) => setSettings({ ...settings, announcement: { ...settings.announcement, linkLabel: v } })} />
                  <Textarea compact label="正文" value={settings.announcement?.body || ''} onChange={(v) => setSettings({ ...settings, announcement: { ...settings.announcement, body: v } })} />
                  <UrlField label="跳转链接" value={settings.announcement?.linkUrl || ''} onChange={(v) => setSettings({ ...settings, announcement: { ...settings.announcement, linkUrl: v } })} optional />
                </div>
                <div className="mt-4">
                  <Textarea label="时间线（时间|内容）" value={timelineText} onChange={setTimelineText} />
                </div>
              </Panel>
              <Panel className="rounded-[16px] p-5">
                <h3 className="font-display text-lg font-semibold">运营设置</h3>
                <Check label="开启自动巡检" checked={settings.operations.inactivityAutoDisable} onChange={(v) => setSettings({ ...settings, operations: { ...settings.operations, inactivityAutoDisable: v } })} />
                <NumberInput label="无记录天数" value={settings.operations.inactiveDays} min={1} onChange={(v) => setSettings({ ...settings, operations: { ...settings.operations, inactiveDays: v } })} />
                <NumberInput label="新用户宽限期" value={settings.operations.newUserGraceDays} min={0} onChange={(v) => setSettings({ ...settings, operations: { ...settings.operations, newUserGraceDays: v } })} />
                <Button variant="secondary" className="mt-4 w-full" loading={busy === 'inactivity'} loadingText="巡检中" onClick={runInactivityCheck}><ShieldCheck size={16} /> 立即巡检</Button>
              </Panel>
            </div>
          </Sheet>
        )}
      </div>
      <AdminFloatingNav tab={tab} setTab={setTab} />

      {/* bulk expiry modal */}
      {bulkExpiryOpen && (
        <Modal
          title="批量补偿有效期"
          onClose={() => setBulkExpiryOpen(false)}
          footer={(
            <div className="flex gap-3">
              <Button variant="secondary" className="flex-1" onClick={() => setBulkExpiryOpen(false)}>取消</Button>
              <Button variant="claret" className="flex-1" loading={busy === 'bulkExpiry'} loadingText="处理中" onClick={submitBulkExpiry}>
                确认给 {bulkPreview?.affected ?? 0} 人 +{bulkExtendDays || 7} 天
              </Button>
            </div>
          )}
        >
          <p className="text-sm leading-6 text-[var(--muted-foreground)]">将为普通用户增加有效期；管理员与长期有效账号不会被修改。适合服务器波动、维护补偿等场景。</p>
          <div className="mt-4 grid gap-4">
            <div>
              <NumberInput label="增加天数" value={bulkExtendDays} min={1} max={3650} onChange={setBulkExtendDays} hint="请输入 1-3650 天之间的整数" />
              <div className="mt-2 grid grid-cols-4 gap-2">
                {[1, 3, 7, 30].map((days) => (
                  <button key={days} type="button" onClick={() => setBulkExtendDays(days)} className={`rounded-xl border px-2 py-2 text-xs font-bold transition ${bulkExtendDays === days ? 'border-[rgba(0,190,227,.75)] bg-[rgba(0,190,227,.16)] text-[var(--primary)]' : 'border-[rgba(231,246,253,.16)] bg-[rgba(255,255,255,.06)] text-[var(--muted-foreground)] hover:bg-[rgba(255,255,255,.10)]'}`}>{days} 天</button>
                ))}
              </div>
            </div>
            <Textarea label="操作备注" value={bulkReason} onChange={setBulkReason} hint="备注会写入操作日志，仅管理员可见。" />
          </div>
          {bulkPreview && (
            <div className="mt-4 space-y-3">
              <div className="rounded-[18px] border border-[rgba(0,190,227,.28)] bg-[rgba(0,190,227,.10)] p-4">
                <p className="text-xs font-bold uppercase tracking-[.16em] text-[var(--primary)]">预计修改</p>
                <p className="mt-1 font-display text-3xl font-black text-[var(--foreground)]">{bulkPreview.affected} 人</p>
                <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">这些普通用户会增加 {bulkExtendDays || 7} 天有效期。</p>
              </div>
              <div className="rounded-[16px] border border-[rgba(231,246,253,.14)] bg-[rgba(255,255,255,.06)] p-4 text-sm leading-7 text-[var(--muted-foreground)]">
                <div className="flex justify-between gap-3"><span>已到期，补偿后会恢复</span><b className="text-[var(--foreground)]">{bulkPreview.reactivatable} 人</b></div>
                <div className="flex justify-between gap-3"><span>已停用，仅延长不启用</span><b className="text-[var(--foreground)]">{bulkPreview.disabled} 人</b></div>
                <div className="flex justify-between gap-3"><span>长期有效，跳过不修改</span><b className="text-[var(--foreground)]">{bulkPreview.permanent} 人</b></div>
                <div className="flex justify-between gap-3"><span>管理员，跳过不修改</span><b className="text-[var(--foreground)]">{bulkPreview.skippedAdmins} 人</b></div>
              </div>
            </div>
          )}
          <StatusNote tone="warning">确认后会立即更新以上预计修改用户；已停用账号不会自动启用，已到期账号若补偿后变为有效，会同步恢复媒体端访问。</StatusNote>
        </Modal>
      )}

      {/* password modal */}
      {pwTarget && (
        <Modal title={`重置 ${pwTarget.username} 的密码`} onClose={() => setPwTarget(null)}>
          <Field label="新密码"><input className="field" type="password" autoFocus value={pwValue} onChange={(e) => setPwValue(e.target.value)} placeholder="输入新密码" /></Field>
          <p className="mt-2 text-xs text-[rgba(166,191,202,.72)]">密码会同步更新到媒体服务器。</p>
          <div className="mt-5 flex gap-3">
            <Button variant="secondary" className="flex-1" onClick={() => setPwTarget(null)}>取消</Button>
            <Button variant="claret" className="flex-1" loading={busy === 'pw'} loadingText="保存中" onClick={submitPassword}>确认重置</Button>
          </div>
        </Modal>
      )}

      {/* expiry modal */}
      {expiryTarget && (
        <Modal title={`调整 ${expiryTarget.username} 的有效期`} onClose={() => setExpiryTarget(null)}>
          <p className="text-sm text-[var(--muted-foreground)]">当前有效期：{expiryTarget.expiresAt ? new Date(expiryTarget.expiresAt).toLocaleString('zh-CN') : '长期有效'}</p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {[7, 30, 90, 365].map((d) => (
              <Button key={d} variant="secondary" loading={busy === 'expiry'} onClick={() => submitExpiry({ extendDays: d })}>+{d} 天</Button>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Button variant="secondary" loading={busy === 'expiry'} onClick={() => submitExpiry({ extendDays: -30 })}>-30 天</Button>
            <Button variant="secondary" loading={busy === 'expiry'} onClick={() => submitExpiry({ clear: true })}>设为长期</Button>
          </div>
          <div className="mt-4 flex justify-end">
            <Button variant="secondary" onClick={() => setExpiryTarget(null)}>关闭</Button>
          </div>
        </Modal>
      )}

      {/* code delete modal */}
      {codeDeleteTarget && (
        <Modal title="删除卡密" onClose={() => setCodeDeleteTarget(null)}>
          <p className="text-sm leading-6 text-[var(--muted-foreground)]">确定删除卡密 <span className="font-mono font-semibold text-[var(--foreground)]">{codeDeleteTarget.code}</span> 吗？删除后列表中不再显示，用户也不能继续使用。</p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCodeDeleteTarget(null)}>取消</Button>
            <Button variant="claret" loading={busy === `delete-code-${codeDeleteTarget.id}`} loadingText="删除中" onClick={deleteCode}><Trash2 size={15} /> 删除</Button>
          </div>
        </Modal>
      )}

      {/* confirm modal */}
      {confirm && (
        <Modal title={confirm.kind === 'delete' ? '删除账号' : confirm.kind === 'disable' ? '停用账号' : '启用账号'} onClose={() => setConfirm(null)}>
          <p className="text-sm leading-6 text-[var(--muted-foreground)]">
            {confirm.kind === 'delete' && <>将删除媒体服务器账号，并从门户列表隐藏 <b className="text-[var(--foreground)]">{confirm.user.username}</b>；后续可用同名重新创建，但原媒体端账号数据无法自动恢复。</>}
            {confirm.kind === 'disable' && <>将停用账号 <b className="text-[var(--foreground)]">{confirm.user.username}</b>，该用户将无法登录媒体服务器。可随时重新启用。</>}
            {confirm.kind === 'enable' && <>将重新启用账号 <b className="text-[var(--foreground)]">{confirm.user.username}</b>，恢复其媒体访问。</>}
          </p>
          <div className="mt-5 flex gap-3">
            <Button variant="secondary" className="flex-1" onClick={() => setConfirm(null)}>取消</Button>
            <Button variant={confirm.kind === 'delete' ? 'claret' : 'claret'} className="flex-1" loading={busy === 'confirm'} loadingText="处理中" onClick={runConfirm}>
              {confirm.kind === 'delete' ? '确认删除' : confirm.kind === 'disable' ? '确认停用' : '确认启用'}
            </Button>
          </div>
        </Modal>
      )}

      {prompt && <PromptModal title={prompt.title} body={prompt.body} onClose={() => setPrompt(null)} />}
    </ShellBackdrop>
  );
}

function DeliveryCard({ username, password, serverUrl }: { username: string; password: string; serverUrl: string }) {
  const text = `你的 MoYin.CC 账号已开通\n账号：${username}\n初始密码：${password}\n服务地址：${serverUrl}\n入口：https://moyin.cc/dashboard\n客户端：EchoShelf 或管理员推荐的兼容客户端`;
  return (
    <div className="space-y-3 text-left">
      <p className="text-sm leading-6 text-[var(--muted-foreground)]">账号创建成功。可直接复制下面这段发给用户：</p>
      <pre className="whitespace-pre-wrap rounded-2xl border border-[rgba(231,246,253,.16)] bg-[rgba(255,255,255,.08)] p-4 text-xs leading-6 text-[var(--foreground)]">{text}</pre>
      <Button variant="claret" className="w-full" onClick={() => navigator.clipboard.writeText(text)}><Copy size={15} /> 复制交付文案</Button>
    </div>
  );
}

function AdminFloatingNav({ tab, setTab }: { tab: AdminTab; setTab: (tab: AdminTab) => void }) {
  const items: Array<{ key: AdminTab; label: string; icon: ReactNode }> = [
    { key: 'overview', label: '概览', icon: <LayoutGrid size={17} /> },
    { key: 'codes', label: '卡密', icon: <KeyRound size={17} /> },
    { key: 'accounts', label: '账号', icon: <UserCog size={17} /> },

    { key: 'users', label: '活跃度', icon: <Users size={17} /> },
    { key: 'settings', label: '配置', icon: <Settings size={17} /> },
  ];
  return (
    <div className="tabbar max-w-xl">
      <div className="side-brand">
        <span className="side-brand-mark">M</span>
        <span><span className="side-brand-title block">MoYin.CC</span><span className="side-brand-sub block">管理台</span></span>
      </div>
      <p className="side-label">管理菜单</p>
      {items.map((item) => (
        <button key={item.key} onClick={() => setTab(item.key)} className={`tab-item ${tab === item.key ? 'tab-item-active' : ''}`}>{item.icon}{item.label}</button>
      ))}
    </div>
  );
}

function DarkStatLight({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[14px] border border-[rgba(231,246,253,.16)] bg-[rgba(255,255,255,.08)] p-4">
      <p className="text-xs uppercase tracking-[.16em] text-[var(--muted-foreground)]">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold text-[var(--foreground)]">{value}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><div className="mt-2">{children}</div></label>;
}

function MiniBtn({ children, onClick, danger }: { children: ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button onClick={onClick} className={`inline-flex min-h-9 items-center gap-1.5 rounded-[10px] border px-3 py-1.5 text-xs font-semibold transition ${danger ? 'border-[rgba(0,190,227,.32)] text-[var(--primary)] hover:bg-[rgba(0,190,227,.10)]' : 'border-[rgba(231,246,253,.16)] text-[var(--foreground)] hover:bg-[rgba(255,255,255,.08)]'}`}>{children}</button>
  );
}

function StatusBadge({ status, isExpired }: { status: string; isExpired: boolean }) {
  const label = isExpired && status === 'active' ? '已到期' : statusLabels[status] || status;
  const tone = status === 'active' && !isExpired ? 'tag-sage' : status === 'disabled' || status === 'deleted' ? 'tag-claret' : 'tag-claret';
  return <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${tone}`}>{label}</span>;
}

function Modal({ title, children, onClose, footer }: { title: string; children: ReactNode; onClose: () => void; footer?: ReactNode }) {
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center overflow-y-auto bg-[rgba(26,23,20,.55)] p-4 pt-[calc(1rem+env(safe-area-inset-top))] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[calc(100dvh-2rem-env(safe-area-inset-top)-env(safe-area-inset-bottom))] w-full max-w-md flex-col overflow-hidden rounded-[20px] border border-[rgba(231,246,253,.16)] bg-[rgba(18,30,45,.96)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 p-6 pb-0">
          <h3 className="display-md text-[1.3rem]">{title}</h3>
          <button onClick={onClose} className="grid size-11 shrink-0 place-items-center rounded-full text-[var(--muted-foreground)] hover:bg-[rgba(255,255,255,.08)]" aria-label="关闭"><X size={18} /></button>
        </div>
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 pb-5 pr-5">{children}</div>
        {footer && <div className="shrink-0 border-t border-[rgba(231,246,253,.12)] bg-[rgba(18,30,45,.98)] p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">{footer}</div>}
      </div>
    </div>
  );
}

function Text({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><input className="field mt-2" value={value || ''} onChange={(e) => onChange(e.target.value)} /></label>;
}
function Textarea({ label, value, onChange, hint, compact = false }: { label: string; value: string; onChange: (v: string) => void; hint?: string; compact?: boolean }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><textarea className={`field mt-2 ${compact ? 'min-h-20' : 'min-h-28'}`} value={value || ''} onChange={(e) => onChange(e.target.value)} />{hint && <span className="mt-1 block text-xs text-[rgba(166,191,202,.72)]">{hint}</span>}</label>;
}
function UrlField({ label, value, onChange, optional = false }: { label: string; value: string; onChange: (v: string) => void; optional?: boolean }) {
  const href = /^https?:\/\//i.test(value.trim()) ? value.trim() : '';
  return (
    <label className="block">
      <span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}{optional ? '（可空）' : ''}</span>
      <div className="mt-2 flex gap-2">
        <input className="field min-w-0 flex-1" type="url" inputMode="url" value={value || ''} onChange={(e) => onChange(e.target.value)} />
        {href && <a className="btn btn-secondary !min-h-11 !px-3" href={href} target="_blank" rel="noreferrer" aria-label={`打开${label}`}><ExternalLink size={15} /></a>}
      </div>
    </label>
  );
}
function NumberInput({ label, value, min = 0, max, disabled, onChange, hint }: { label: string; value: number; min?: number; max?: number; disabled?: boolean; onChange: (v: number) => void; hint?: string }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><input className="field mt-2 disabled:opacity-50" type="number" min={min} max={max} disabled={disabled} value={value} onChange={(e) => onChange(Math.max(min, Number(e.target.value) || min))} />{hint && <span className="mt-1 block text-xs text-[rgba(166,191,202,.72)]">{hint}</span>}</label>;
}
function Select({ label, value, onChange, options, hint }: { label: string; value: string; onChange: (v: string) => void; options: Array<[string, string]>; hint?: string }) {
  return <label className="block"><span className="text-sm font-semibold text-[var(--muted-foreground)]">{label}</span><select className="field mt-2" value={value} onChange={(e) => onChange(e.target.value)}>{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>{hint && <span className="mt-1 block text-xs text-[rgba(166,191,202,.72)]">{hint}</span>}</label>;
}
function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <label className="mt-3 flex min-h-12 items-center justify-between gap-3 rounded-[12px] border border-[rgba(231,246,253,.12)] bg-[rgba(255,255,255,.08)] px-4 py-3 text-sm font-semibold text-[var(--foreground)]"><span>{label}</span><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-[var(--primary)]" /></label>;
}
function CheckPanel({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <label className="flex min-h-[6rem] items-center justify-between gap-3 rounded-[16px] border border-[rgba(231,246,253,.16)] bg-[rgba(255,255,255,.08)] p-4 text-sm font-semibold text-[var(--foreground)]"><span>{label}</span><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-[var(--primary)]" /></label>;
}
