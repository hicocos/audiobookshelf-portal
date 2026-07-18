'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  BookPlus, CalendarRange, Clock, Compass, Copy, Download, Gift, Headphones, KeyRound, LinkIcon, ListMusic,
  LogOut, Monitor, RefreshCcw, Send, ShieldCheck, Smartphone, Sparkles, Ticket, UserRound,
} from 'lucide-react';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { NavDrawer } from '@/components/nav-drawer';
import { AccessibleModal } from '@/components/accessible-modal';
import { Button, LoadingScreen, Panel, PromptModal, SectionHeader, Sheet, ShellBackdrop, Stat, StatusNote, WordMark, AnnouncementBanner } from '@/components/ui';
import {
  api, ApiError, clearSession, DEFAULT_TELEGRAM_SETTINGS, LeaderboardEntry, LibrarySummary, MediaRequestRecord, PortalUser,
  PublicSettings, ReferralRecord, RewardSummary, TelegramBindTokenResponse, UserCapabilities,
} from '@/lib/api';
import { formatShanghaiDateTime } from '@/lib/datetime';

const statusText: Record<string, string> = { active: '正常', expired: '已到期', disabled: '已停用', deleted: '需处理', pending: '待启用' };
const statusHelp: Record<string, string> = {
  active: '账号正常，可以继续在客户端收听。',
  expired: '账号已到期，客户端暂不可听；兑换续期码后会恢复。',
  disabled: '账号被管理员停用，请联系管理员处理。',
  deleted: '账号状态异常，请联系管理员重新确认。',
  pending: '账号待启用，请等待管理员处理。',
};
const roleText: Record<string, string> = { user: '用户', admin: '管理员', root: '超级管理员' };
const rewardKindText: Record<string, string> = { daily_checkin: '每日签到', referral_reward: '邀请奖励', redeem_expiry_days: '兑换有效期', admin_adjustment: '管理员调整' };
const requestStatusText: Record<string, string> = { pending: '待处理', accepted: '已受理', available: '已上架', rejected: '未采纳' };
const fallbackSettings: PublicSettings = {
  siteName: 'MoYin.CC', tagline: '安静的声音栖地', registrationEnabled: true, passwordMinLength: 3,
  copy: { heroKicker: 'AUDIO ISLAND', heroTitle: 'MoYin.CC', heroSubtitle: '安静的声音栖地', primaryCta: '申请访问', secondaryCta: '进入账号中心', notice: '一个轻量、安静、专注的音频内容入口。' },
  links: { libraryUrl: '', supportUrl: '', announcementUrl: '' },
  client: { serverUrl: 'https://listen.moyin.cc', androidDownloadUrl: 'https://mikupan.com/s/AOrU0', iosGuideText: '在 App Store 搜索“EchoShelf”并安装。', desktopGuideText: '暂无稳定方案，建议使用手机或平板。' },
  announcement: { title: '', body: '', linkUrl: '', linkLabel: '', timeline: [] },
  features: { registration: true, showLibraryEntry: false, showSupportEntry: false, showAnnouncements: true },
  operations: { inactivityAutoDisable: false, inactiveDays: 30, newUserGraceDays: 7, lastInactivityCheckAt: null, lastInactivityDisabled: 0 },
  telegram: { ...DEFAULT_TELEGRAM_SETTINGS },
  sections: { benefits: [], steps: [], faq: [] },
};
type Tab = 'account' | 'rewards' | 'requests' | 'guide' | 'records';
type ClientKey = 'mobile' | 'desktop' | 'notes';

export default function DashboardPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>('account');
  const [client, setClient] = useState<ClientKey>('mobile');
  const [user, setUser] = useState<PortalUser | null>(null);
  const [capabilities, setCapabilities] = useState<UserCapabilities | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [summary, setSummary] = useState<LibrarySummary | null>(null);
  const [rewards, setRewards] = useState<RewardSummary | null>(null);
  const [referrals, setReferrals] = useState<ReferralRecord[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [requests, setRequests] = useState<MediaRequestRecord[]>([]);
  const [redeemDays, setRedeemDays] = useState(1);
  const [requestForm, setRequestForm] = useState<{ kind: 'book' | 'podcast'; title: string; details: string }>({ kind: 'book', title: '', details: '' });
  const [featureBusy, setFeatureBusy] = useState('');
  const [code, setCode] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [redeeming, setRedeeming] = useState(false);
  const [popup, setPopup] = useState<{ title: string; body: string } | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  const [pwCurrent, setPwCurrent] = useState('');
  const [pwNext, setPwNext] = useState('');
  const [pwConfirm, setPwConfirm] = useState('');
  const [pwSaving, setPwSaving] = useState(false);
  const [tgBindToken, setTgBindToken] = useState<TelegramBindTokenResponse | null>(null);
  const [tgSaving, setTgSaving] = useState(false);
  const [tgUnbindConfirm, setTgUnbindConfirm] = useState(false);
  const minPwLength = settings?.passwordMinLength ?? 1;
  const siteName = settings?.siteName || 'MoYin.CC';
  const serverAddress = settings?.client?.serverUrl || fallbackSettings.client.serverUrl;
  const androidDownloadUrl = settings?.client?.androidDownloadUrl || fallbackSettings.client.androidDownloadUrl;
  const iosGuideText = settings?.client?.iosGuideText || fallbackSettings.client.iosGuideText;
  const desktopGuideText = settings?.client?.desktopGuideText || fallbackSettings.client.desktopGuideText;
  const supportUrl = settings?.features?.showSupportEntry ? settings?.links?.supportUrl?.trim() : '';

  async function loadAll() {
    setLoading(true);
    try {
      const results = await Promise.allSettled([
        api.config(),
        api.me(),
      ]);
      const loadedSettings = results[0].status === 'fulfilled' ? results[0].value : fallbackSettings;
      const loadedUser = results[1].status === 'fulfilled' ? results[1].value.user : null;
      const loadedCapabilities = results[1].status === 'fulfilled' ? results[1].value.capabilities : null;
      setSettings(loadedSettings);
      if (loadedUser) setUser(loadedUser);
      if (loadedCapabilities) setCapabilities(loadedCapabilities);
      if (results[0].status === 'rejected') {
        setSettings(fallbackSettings);
      }
      if (results[1].status === 'rejected') {
        const error = results[1].reason;
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          router.replace('/login?next=/dashboard');
          return;
        }
        setMessage(error instanceof Error ? error.message : '账号信息加载失败，请稍后重试。');
      }
      if (loadedCapabilities?.canListen) {
        try {
          setSummary(await api.librarySummary());
        } catch {
          setMessage((current) => current || '收听数据暂时不可用，可稍后点击刷新。');
        }
      } else {
        setSummary(null);
      }
      if (loadedCapabilities) {
        const optional: Array<Promise<unknown>> = [];
        if (loadedCapabilities.canCheckin || loadedCapabilities.canRedeemPoints || loadedCapabilities.canRefer || loadedCapabilities.canViewLeaderboard) {
          optional.push(api.rewards().then(setRewards));
        }
        if (loadedCapabilities.canRefer) optional.push(api.referrals().then((value) => setReferrals(value.items)));
        if (loadedCapabilities.canRequest) optional.push(api.mediaRequests().then((value) => setRequests(value.items)));
        if (loadedCapabilities.canViewLeaderboard) optional.push(api.leaderboard().then((value) => setLeaderboard(value.entries)));
        await Promise.allSettled(optional);
      }
    } finally {
      setLoading(false);
      setHasLoaded(true);
    }
  }
  useEffect(() => { void loadAll(); }, []);
  useEffect(() => {
    const saved = window.sessionStorage.getItem('moyin-dashboard-tab');
    if (saved && ['account', 'rewards', 'requests', 'guide', 'records'].includes(saved)) setTab(saved as Tab);
  }, []);
  useEffect(() => { window.sessionStorage.setItem('moyin-dashboard-tab', tab); }, [tab]);

  async function redeem() {
    if (redeeming) return;
    if (!code.trim()) { setMessage('请输入续期码。'); return; }
    setMessage('');
    setRedeeming(true);
    try {
      const r = await api.redeem(code.trim());
      setUser(r.user);
      setCode('');
      const nowPermanent = r.user?.expiresAt == null;
      setPopup({
        title: r.upstreamReactivated === false ? '续期已记录' : '续期成功',
        body: r.upstreamReactivated === false
          ? (r.message || '续期已记录，但媒体账号恢复失败，请联系管理员；不要重复兑换续期码。')
          : nowPermanent
            ? '续期成功，你的账号现在为永久有效。媒体账号已恢复。'
            : `续期成功，新的有效期至 ${formatShanghaiDateTime(r.user!.expiresAt!)}，媒体账号已恢复。`,
      });
      setMessage(r.message || '续期成功，新的有效期已更新。');
    } catch (err) {
      const text = err instanceof Error ? err.message : '兑换失败';
      // Already-permanent and wrong-purpose cases surface as a popup so the
      // user clearly understands why the code was not applied.
      if (text.includes('永久有效') || text.includes('续期码') || text.includes('邀请码')) {
        setPopup({ title: '无法续期', body: text });
      }
      setMessage(text);
    } finally {
      setRedeeming(false);
    }
  }

  async function logout() {
    setLoggingOut(true);
    try { await clearSession(); } finally { location.href = '/login'; }
  }

  async function changePassword() {
    if (pwSaving) return;
    setMessage('');
    if (!pwCurrent) {
      setMessage('请输入当前密码。');
      return;
    }
    if (pwNext.length < minPwLength) {
      setMessage(`新密码至少需要 ${minPwLength} 位。`);
      return;
    }
    if (pwNext !== pwConfirm) {
      setMessage('两次输入的新密码不一致，请重新确认。');
      return;
    }
    setPwSaving(true);
    try {
      await api.changePassword(pwCurrent, pwNext);
      setPwCurrent('');
      setPwNext('');
      setPwConfirm('');
      setPopup({ title: '密码修改成功', body: '听书 App 请用新密码登录。' });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '密码修改失败');
    } finally {
      setPwSaving(false);
    }
  }

  async function generateTelegramBindToken() {
    if (tgSaving) return;
    setMessage('');
    setTgSaving(true);
    try {
      const result = await api.generateTelegramBindToken();
      setTgBindToken(result);
      setMessage('Telegram 绑定码已生成，请在有效期内发送给 Bot。');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '生成 Telegram 绑定码失败');
    } finally {
      setTgSaving(false);
    }
  }

  async function unbindTelegram() {
    if (tgSaving) return;
    setMessage('');
    setTgSaving(true);
    try {
      const result = await api.unbindTelegram();
      setUser(result.user);
      setTgBindToken(null);
      setPopup({ title: '已解绑 Telegram', body: '如需重新绑定，请重新生成绑定码并在 Bot 中使用。' });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '解绑 Telegram 失败');
    } finally {
      setTgSaving(false);
    }
  }

  async function exportMyData() {
    setFeatureBusy('export');
    setMessage('');
    try {
      const data = await api.exportMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `moyin-data-${user?.username || 'account'}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setMessage('个人数据副本已生成。文件仅保存在你的设备上，请妥善保管。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '个人数据导出失败。');
    } finally {
      setFeatureBusy('');
    }
  }

  async function checkin() {
    setFeatureBusy('checkin');
    setMessage('');
    try {
      const result = await api.checkin();
      setRewards(await api.rewards());
      setMessage(result.alreadyCheckedIn ? `今天已经签到，当前连续 ${result.streak} 天。` : `签到成功，获得 ${result.pointsAwarded} 积分。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '签到失败。');
    } finally {
      setFeatureBusy('');
    }
  }

  async function redeemRewardDays() {
    setFeatureBusy('redeem-points');
    setMessage('');
    try {
      const result = await api.redeemPoints(redeemDays, crypto.randomUUID());
      setRewards(await api.rewards());
      setUser((current) => current ? { ...current, expiresAt: result.expiresAt, status: 'active' } : current);
      setPopup({ title: '积分兑换成功', body: `已用 ${result.cost} 积分兑换 ${result.days} 天，有效期已同步到媒体账号。` });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '积分兑换失败。');
    } finally {
      setFeatureBusy('');
    }
  }

  async function createReferral() {
    setFeatureBusy('referral');
    setMessage('');
    try {
      const result = await api.createReferral();
      const history = await api.referrals();
      setReferrals(history.items);
      setPopup({ title: result.existing ? '已有可用邀请码' : '邀请码已生成', body: `${result.code}\n有效期至 ${formatShanghaiDateTime(result.expiresAt)}，好友注册成功后你可获得 ${result.rewardPoints} 积分。` });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '邀请码生成失败。');
    } finally {
      setFeatureBusy('');
    }
  }

  async function toggleLeaderboard() {
    const enabled = !rewards?.leaderboardOptIn;
    setFeatureBusy('leaderboard');
    setMessage('');
    try {
      await api.setLeaderboardOptIn(enabled);
      const [summaryResult, leaderboardResult] = await Promise.all([api.rewards(), api.leaderboard()]);
      setRewards(summaryResult);
      setLeaderboard(leaderboardResult.entries);
      setMessage(enabled ? '已自愿加入匿名积分榜。' : '已退出匿名积分榜。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '排行榜设置失败。');
    } finally {
      setFeatureBusy('');
    }
  }

  async function submitMediaRequest() {
    if (!requestForm.title.trim()) {
      setMessage('请填写作品名称。');
      return;
    }
    setFeatureBusy('request');
    setMessage('');
    try {
      const result = await api.createMediaRequest({ ...requestForm, title: requestForm.title.trim(), details: requestForm.details.trim() || undefined });
      setRequests((current) => [result.item, ...current]);
      setRequestForm({ kind: 'book', title: '', details: '' });
      setMessage('请求已提交，处理状态会显示在本页。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '请求提交失败。');
    } finally {
      setFeatureBusy('');
    }
  }

  const isAdmin = Boolean(capabilities?.canAdmin);
  const showRewards = Boolean(capabilities && (capabilities.canCheckin || capabilities.canRedeemPoints || capabilities.canRefer || capabilities.canViewLeaderboard));
  const showRequests = Boolean(capabilities?.canRequest);
  useEffect(() => {
    if (
      (tab === 'rewards' && !showRewards)
      || (tab === 'requests' && !showRequests)
      || (tab === 'records' && capabilities != null && !capabilities.canListen)
    ) {
      setTab('account');
    }
  }, [capabilities, showRequests, showRewards, tab]);
  const expiresText = isAdmin ? '管理员长期有效' : user?.expiresAt ? formatShanghaiDateTime(user.expiresAt) : '永久有效';
  const daysLeft = isAdmin ? null : user?.expiresAt ? Math.ceil((new Date(user.expiresAt).getTime() - Date.now()) / 86400000) : null;

  const latest = useMemo(
    () => [...(summary?.progress || [])].sort((a, b) => new Date(b.lastUpdate || 0).getTime() - new Date(a.lastUpdate || 0).getTime())[0],
    [summary?.progress],
  );
  const nextStep = useMemo(() => {
    if (!user) return { title: '读取账号状态中', body: '稍等片刻，账号中心会显示下一步建议。', action: null as Tab | null };
    if (user.status === 'expired') return { title: '账号已到期', body: '先兑换续期码恢复访问；续期后再回到客户端收听。', action: 'account' as Tab };
    if (user.status === 'disabled' || user.status === 'deleted') return { title: '需要管理员处理', body: '账号暂不可用，请联系管理员确认媒体账号状态。', action: null as Tab | null };
    if (daysLeft !== null && daysLeft <= 7) return { title: '即将到期', body: '建议提前兑换续期码，避免客户端突然无法收听。', action: 'account' as Tab };
    if (!summary?.progress?.length) return { title: '先配置客户端', body: '复制服务地址，按教程添加到 EchoShelf 后登录账号。', action: 'guide' as Tab };
    return { title: '继续收听', body: latest ? `最近收听《${latest.title}》，可回到客户端继续。` : '你的账号正常，可继续在客户端收听。', action: 'records' as Tab };
  }, [user, daysLeft, summary?.progress, latest]);
  const avgProgress = useMemo(() => {
    const items = summary?.progress || [];
    if (!items.length) return 0;
    return Math.round(items.reduce((sum, item) => sum + item.progressPercent, 0) / items.length);
  }, [summary?.progress]);
  return (
    <ShellBackdrop className="px-4 pb-8 pt-5 sm:px-6 sm:pt-7">
      {loading && !hasLoaded && <LoadingScreen title="正在加载账号中心" subtitle="loading" />}
      {loggingOut && <LoadingScreen title="正在退出" subtitle="see you" />}
      <div className="app-content relative" data-nav-drawer-background>
        {/* top bar */}
        <nav className="flex items-center justify-between py-2">
          <div className="flex items-center gap-2.5">
            <Link href="/"><WordMark siteName={siteName} tagline="账号 · 续期 · 教程 · 进度" small /></Link>
            <AnnouncementBanner
              show={settings?.features?.showAnnouncements}
              title={settings?.announcement?.title}
              body={settings?.announcement?.body}
              linkUrl={settings?.announcement?.linkUrl}
              linkLabel={settings?.announcement?.linkLabel}
              timeline={settings?.announcement?.timeline}
            />
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" className="!min-h-10 !px-4 text-sm" loading={loggingOut} loadingText="退出中" onClick={logout}>
              <LogOut size={15} /> 退出
            </Button>
          </div>
        </nav>

        <hr className="hr-fade my-3" />

        {message && <div className="mb-4"><StatusNote tone={message.includes('成功') ? 'success' : message.includes('请先登录') ? 'warning' : 'neutral'}>{message}</StatusNote></div>}

        {/* ACCOUNT */}
        {tab === 'account' && (
          <div className="space-y-5">
            <Sheet className="rounded-[22px] p-6 sm:p-9">
              <div className="flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between">
                <div className="min-w-0">
                  <p className="kicker !text-[var(--primary)]">账号中心</p>
                  <h1 className="display-lg mt-3 text-[var(--foreground)]">{isAdmin ? '账号概览' : user?.username || '未登录'}</h1>
                  <p className="mt-4 max-w-xl leading-7 text-[var(--muted-foreground)]">
                    在这里查看账号状态和有效期，也可以续期、配置客户端并管理收听进度。
                  </p>
                </div>
                <div className="account-health-card max-w-sm shrink-0 rounded-[16px] border border-[rgba(231,246,253,.12)] bg-white/5 p-5">
                  <p className="text-xs uppercase tracking-[.2em] text-[rgba(166,191,202,.72)]">当前状态</p>
                  <p className="mt-2 font-display text-2xl font-semibold text-[var(--foreground)]">{nextStep.title}</p>
                  <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{nextStep.body}</p>
                </div>
              </div>
            </Sheet>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Info title="账号状态" value={user?.status ? statusText[user.status] || user.status : '-'} icon={<ShieldCheck size={16} />} />
              <Info title="账号角色" value={user?.role ? roleText[user.role] || user.role : '-'} icon={<UserRound size={16} />} />
              <Info title="有效期至" value={expiresText} icon={<CalendarRange size={16} />} />
              <Info title="剩余天数" value={isAdmin ? '不受限' : daysLeft == null ? '永久' : daysLeft > 0 ? `${daysLeft} 天` : '已到期'} icon={<Clock size={16} />} />
              <Info title="服务器地址" value={serverAddress} icon={<LinkIcon size={16} />} action={<CopyButton text={serverAddress} label="复制" />} />
            </div>

            <Panel className="rounded-[16px] p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3">
                  <Compass className="mt-0.5 shrink-0 text-[var(--primary)]" size={18} />
                  <div>
                    <p className="font-display font-semibold">{nextStep.title}</p>
                    <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{nextStep.body}</p>
                  </div>
                </div>
                {nextStep.action && <Button variant="secondary" className="shrink-0" onClick={() => setTab(nextStep.action!)}>查看下一步</Button>}
              </div>
            </Panel>

            <Panel className="rounded-[16px] p-5">
              <div className="flex items-start gap-3">
                <ShieldCheck className="mt-0.5 shrink-0 text-[var(--primary)]" size={18} />
                <div>
                  <p className="font-display font-semibold">{user?.status ? statusText[user.status] || user.status : '账号状态'}</p>
                  <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{user?.status ? statusHelp[user.status] || '请联系管理员确认账号状态。' : '正在读取账号状态。'}</p>
                  {supportUrl && <a className="mt-3 inline-flex items-center gap-1.5 text-sm font-black text-[var(--primary)] underline underline-offset-4" href={supportUrl} target="_blank" rel="noreferrer">遇到问题？联系管理员 <LinkIcon size={14} /></a>}
                </div>
              </div>
            </Panel>

            <div className="grid gap-5 lg:grid-cols-[1fr_.85fr]">
              {capabilities?.canRenew ? (
                <Sheet className="rounded-[20px] p-6 sm:p-8">
                  <SectionHeader eyebrow="账号续期" title="兑换续期码" body="输入管理员发放的续期码，即可延长账号有效期。永久续期码可让账号长期使用。" />
                  <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto]">
                    <label className="block"><span className="mb-2 block text-sm font-black">续期码</span><input className="field font-mono tracking-[.12em]" placeholder="例如 RENEW-XXXX" value={code}
                      onChange={(e) => setCode(e.target.value.toUpperCase())} onKeyDown={(e) => { if (e.key === 'Enter') void redeem(); }} /></label>
                    <Button variant="claret" loading={redeeming} loadingText="兑换中" onClick={redeem}><Ticket size={16} /> 立即续期</Button>
                  </div>
                </Sheet>
              ) : (
                <Panel className="rounded-[20px] p-6 sm:p-8">
                  <p className="font-display font-semibold">续期暂不可用</p>
                  <p className="mt-2 text-sm text-[var(--muted-foreground)]">{capabilities?.unavailableReasons.renew || '续期功能当前未开放。'}</p>
                </Panel>
              )}
              <Sheet className="rounded-[20px] p-6 sm:p-8">
                <SectionHeader eyebrow="收听概览" title="最近进度" body={latest ? `《${latest.title}》已收听 ${latest.progressPercent}%` : '开始收听后，这里会显示最近的进度摘要。'} />
                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  <Stat label="收听记录" value={`${summary?.stats.progressCount ?? 0} 条`} />
                  <Stat label="平均进度" value={`${avgProgress}%`} />
                </div>
              </Sheet>
            </div>

            <Sheet className="rounded-[20px] p-6 sm:p-8">
              <SectionHeader eyebrow="Telegram" title="绑定 Telegram Bot" body="绑定后可在 Bot 中查看账号状态、媒体库摘要，并使用后续自助流程。绑定码只显示一次，10 分钟内有效。" />
              <div className="mt-6 space-y-4">
                {user?.telegramBound ? (
                  <Panel className="rounded-[16px] p-5">
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="font-display font-semibold">已绑定 {user.telegramUsername ? `@${user.telegramUsername}` : 'Telegram 账号'}</p>
                        <p className="mt-2 text-sm text-[var(--muted-foreground)]">
                          绑定时间：{user.telegramBoundAt ? formatShanghaiDateTime(user.telegramBoundAt) : '未知'}
                        </p>
                      </div>
                      <Button variant="secondary" loading={tgSaving} loadingText="解绑中" onClick={() => setTgUnbindConfirm(true)}>解绑 Telegram</Button>
                    </div>
                  </Panel>
                ) : (
                  <Panel className="rounded-[16px] p-5">
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="font-display font-semibold">尚未绑定 Telegram</p>
                        <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">点击生成绑定码后，在 Telegram Bot 中发送命令即可完成绑定。不要把绑定码发给别人。</p>
                      </div>
                      <Button variant="claret" loading={tgSaving} loadingText="生成中" onClick={generateTelegramBindToken}>生成绑定码</Button>
                    </div>
                    {tgBindToken && (
                      <div className="mt-5 rounded-[14px] border border-[rgba(231,246,253,.16)] bg-black/20 p-4">
                        <p className="text-xs tracking-[.12em] text-[rgba(166,191,202,.72)]">绑定命令</p>
                        <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <code className="break-all rounded-lg bg-black/30 px-3 py-2 font-mono text-sm text-[var(--foreground)]">{tgBindToken.command}</code>
                          <CopyButton text={tgBindToken.command} label="复制命令" />
                        </div>
                        {tgBindToken.botUsername && <a className="btn btn-primary mt-3 w-full" href={`https://t.me/${tgBindToken.botUsername.replace(/^@/, '')}?start=bind_${encodeURIComponent(tgBindToken.code)}`} target="_blank" rel="noreferrer"><Send size={15} /> 一键打开 Bot 并绑定</a>}
                        <p className="mt-3 text-xs text-[var(--muted-foreground)]">有效期至：{formatShanghaiDateTime(tgBindToken.expiresAt)}</p>
                        {tgBindToken.botUsername && <p className="mt-1 text-xs text-[var(--muted-foreground)]">Bot：@{tgBindToken.botUsername}</p>}
                      </div>
                    )}
                  </Panel>
                )}
              </div>
            </Sheet>

            <Sheet className="rounded-[20px] p-6 sm:p-8">
              <SectionHeader eyebrow="账号安全" title="修改密码" body="新密码会同步到听书客户端。修改后，请在客户端使用新密码重新登录。用户名不区分大小写。" />
              <div className="mt-6 grid gap-3 sm:grid-cols-3">
                <input className="field" type="password" autoComplete="current-password" placeholder="当前密码"
                  value={pwCurrent} onChange={(e) => setPwCurrent(e.target.value)} />
                <input className="field" type="password" autoComplete="new-password" placeholder={`新密码（至少 ${minPwLength} 位）`}
                  value={pwNext} onChange={(e) => setPwNext(e.target.value)} />
                <input className="field" type="password" autoComplete="new-password" placeholder="确认新密码"
                  value={pwConfirm} onChange={(e) => setPwConfirm(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') void changePassword(); }} />
              </div>
              <div className="mt-4 flex justify-end">
                <Button variant="claret" loading={pwSaving} loadingText="保存中"
                  disabled={!pwCurrent || !pwNext || !pwConfirm} onClick={changePassword}>
                  <KeyRound size={16} /> 保存新密码
                </Button>
              </div>
            </Sheet>

            <Sheet className="rounded-[20px] p-6 sm:p-8">
              <SectionHeader eyebrow="隐私与数据" title="查看和带走你的数据" body="可下载门户保存的账号资料、兑换记录、内容请求和积分流水。收听活动由媒体服务器保存，如需完整副本或申请注销，请联系管理员。" />
              <div className="mt-5 flex flex-wrap gap-3">
                <Button variant="secondary" loading={featureBusy === 'export'} loadingText="生成中" onClick={exportMyData}><Download size={15} /> 导出个人数据</Button>
                <Link className="btn btn-secondary" href="/privacy">隐私说明</Link>
                <Link className="btn btn-secondary" href="/terms">服务条款</Link>
              </div>
            </Sheet>
          </div>
        )}

        {/* REWARDS */}
        {tab === 'rewards' && showRewards && (
          <div className="space-y-5">
            <Sheet className="rounded-[22px] p-6 sm:p-9">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <SectionHeader eyebrow="用户权益" title="签到、积分与邀请" body="每天签到积累积分，可兑换账号有效期；邀请好友注册成功后也会获得奖励。" />
                {capabilities?.canCheckin && <Button variant="claret" loading={featureBusy === 'checkin'} loadingText="签到中" onClick={checkin}><Sparkles size={16} /> 今日签到</Button>}
              </div>
              <div className="mt-7 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="当前积分" value={`${rewards?.balance ?? 0}`} />
                <Stat label="累计获得" value={`${rewards?.lifetimeEarned ?? 0}`} />
                <Stat label="连续签到" value={`${rewards?.streak ?? 0} 天`} />
                <Stat label="上次签到" value={rewards?.lastCheckinDate || '尚未签到'} />
              </div>
            </Sheet>

            <div className="grid gap-5 lg:grid-cols-2">
              {capabilities?.canRedeemPoints && (
                <Sheet className="rounded-[20px] p-6 sm:p-8">
                  <SectionHeader eyebrow="积分续期" title="兑换有效期" body={`每 ${settings?.telegram.pointsPerDay ?? 100} 积分可兑换 1 天，单次最多 ${settings?.telegram.maxRedeemDays ?? 30} 天。`} />
                  <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto]">
                    <input className="field" type="number" min={1} max={settings?.telegram.maxRedeemDays ?? 30} value={redeemDays} onChange={(event) => setRedeemDays(Number(event.target.value))} />
                    <Button variant="claret" loading={featureBusy === 'redeem-points'} loadingText="兑换中" onClick={redeemRewardDays}><Gift size={16} /> 兑换天数</Button>
                  </div>
                </Sheet>
              )}

              {capabilities?.canRefer && (
                <Sheet className="rounded-[20px] p-6 sm:p-8">
                  <SectionHeader eyebrow="好友邀请" title="生成注册邀请码" body={`每月最多生成 ${settings?.telegram.referralMonthlyLimit ?? 3} 个，好友注册成功后奖励 ${settings?.telegram.referralRewardPoints ?? 50} 积分。`} />
                  <Button variant="secondary" className="mt-6 w-full" loading={featureBusy === 'referral'} loadingText="生成中" onClick={createReferral}><Send size={16} /> 生成邀请码</Button>
                </Sheet>
              )}
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <Sheet className="rounded-[20px] p-6 sm:p-8">
                <h3 className="font-display text-xl font-semibold">积分明细</h3>
                <div className="mt-5 grid gap-3">
                  {(rewards?.history || []).map((item, index) => (
                    <Panel key={`${item.createdAt}-${index}`} className="flex items-center justify-between gap-3 rounded-[14px] p-4">
                      <div><p className="font-semibold">{rewardKindText[item.kind] || item.kind}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{formatShanghaiDateTime(item.createdAt)}</p></div>
                      <div className="text-right"><p className={item.amount >= 0 ? 'text-emerald-300' : 'text-red-300'}>{item.amount >= 0 ? '+' : ''}{item.amount}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">余额 {item.balanceAfter}</p></div>
                    </Panel>
                  ))}
                  {!rewards?.history.length && <p className="py-6 text-center text-sm text-[var(--muted-foreground)]">暂无积分记录。</p>}
                </div>
              </Sheet>

              {capabilities?.canRefer && (
                <Sheet className="rounded-[20px] p-6 sm:p-8">
                  <h3 className="font-display text-xl font-semibold">邀请记录</h3>
                  <div className="mt-5 grid gap-3">
                    {referrals.map((item) => (
                      <Panel key={item.id} className="rounded-[14px] p-4">
                        <div className="flex items-start justify-between gap-3"><code className="break-all font-mono font-semibold">{item.code || '邀请码已失效'}</code>{item.code && <CopyButton text={item.code} label="复制" />}</div>
                        <p className="mt-2 text-xs text-[var(--muted-foreground)]">{item.used ? '已使用' : '待使用'} · 奖励 {item.rewardPoints} 积分 · 有效期至 {formatShanghaiDateTime(item.expiresAt)}</p>
                      </Panel>
                    ))}
                    {!referrals.length && <p className="py-6 text-center text-sm text-[var(--muted-foreground)]">暂无邀请记录。</p>}
                  </div>
                </Sheet>
              )}
            </div>

            {capabilities?.canViewLeaderboard && (
              <Sheet className="rounded-[20px] p-6 sm:p-8">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <SectionHeader eyebrow="自愿参与" title="匿名积分榜" body="只显示主动参与者、匿名用户名和累计积分，不展示收听行为或 Telegram 信息。" />
                  <Button variant="secondary" loading={featureBusy === 'leaderboard'} loadingText="更新中" onClick={toggleLeaderboard}>
                    {rewards?.leaderboardOptIn ? '退出排行榜' : '自愿加入排行榜'}
                  </Button>
                </div>
                <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {leaderboard.map((item) => (
                    <Panel key={`${item.rank}-${item.displayName}`} className="flex items-center justify-between gap-4 rounded-[14px] p-4">
                      <div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-full tag-gold font-display font-semibold">{item.rank}</span><p className="font-semibold">{item.displayName}</p></div>
                      <p className="font-display text-lg font-semibold text-[var(--primary)]">{item.lifetimeEarned} 分</p>
                    </Panel>
                  ))}
                  {!leaderboard.length && <p className="py-6 text-sm text-[var(--muted-foreground)]">暂时还没有用户自愿参与排行榜。</p>}
                </div>
              </Sheet>
            )}
          </div>
        )}

        {/* REQUESTS */}
        {tab === 'requests' && showRequests && (
          <div className="space-y-5">
            <Sheet className="rounded-[22px] p-6 sm:p-9">
              <SectionHeader eyebrow="内容请求" title="求书 / 播客" body="提交想听的有声书或播客。最多同时保留 3 个待处理请求，管理员处理后状态会在这里更新。" />
              <div className="mt-7 grid gap-4 lg:grid-cols-[.35fr_1fr]">
                <label><span className="mb-2 block text-sm font-black">请求类型</span><select className="field" value={requestForm.kind} onChange={(event) => setRequestForm({ ...requestForm, kind: event.target.value as 'book' | 'podcast' })}>
                  <option value="book">有声书</option><option value="podcast">播客</option>
                </select></label>
                <label><span className="mb-2 block text-sm font-black">作品名称</span><input className="field" placeholder="必填" value={requestForm.title} onChange={(event) => setRequestForm({ ...requestForm, title: event.target.value })} /></label>
              </div>
              <label className="mt-4 block"><span className="mb-2 block text-sm font-black">补充信息（可选）</span><textarea className="field min-h-28" placeholder="作者、主播、版本、链接等" value={requestForm.details} onChange={(event) => setRequestForm({ ...requestForm, details: event.target.value })} /></label>
              <div className="mt-4 flex justify-end"><Button variant="claret" loading={featureBusy === 'request'} loadingText="提交中" onClick={submitMediaRequest}><BookPlus size={16} /> 提交请求</Button></div>
            </Sheet>

            <Sheet className="rounded-[20px] p-6 sm:p-8">
              <div className="flex items-center justify-between gap-4"><h3 className="font-display text-xl font-semibold">我的请求</h3><Button variant="secondary" onClick={async () => setRequests((await api.mediaRequests()).items)}><RefreshCcw size={15} /> 刷新</Button></div>
              <div className="mt-5 grid gap-3">
                {requests.map((item) => (
                  <Panel key={item.id} className="rounded-[16px] p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-display text-lg font-semibold">{item.title}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{item.kind === 'book' ? '有声书' : '播客'} · {formatShanghaiDateTime(item.createdAt)}</p></div><span className="rounded-full tag-gold px-3 py-1 text-xs font-semibold">{requestStatusText[item.status] || item.status}</span></div>
                    {item.details && <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{item.details}</p>}
                    {item.adminNote && <p className="mt-3 rounded-xl bg-white/5 p-3 text-sm">管理员备注：{item.adminNote}</p>}
                  </Panel>
                ))}
                {!requests.length && <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">还没有提交内容请求。</p>}
              </div>
            </Sheet>
          </div>
        )}

        {/* GUIDE */}
        {tab === 'guide' && (
          <div className="space-y-5">
            <Sheet className="rounded-[22px] p-6 sm:p-9">
              <SectionHeader eyebrow="客户端设置" title="使用教程" />
              <div className="mt-7 grid gap-3 sm:grid-cols-3">
                <ClientTab active={client === 'mobile'} onClick={() => setClient('mobile')} icon={<Smartphone size={17} />} title="手机端" body="手机端收听说明" />
                <ClientTab active={client === 'desktop'} onClick={() => setClient('desktop')} icon={<Monitor size={17} />} title="电脑端" body="桌面收听说明" />
                <ClientTab active={client === 'notes'} onClick={() => setClient('notes')} icon={<ShieldCheck size={17} />} title="注意事项" body="使用须知与建议" />
              </div>
              <Panel className="mt-5 flex flex-col gap-3 rounded-[16px] p-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-display font-semibold">听书服务器地址</p>
                  <p className="mt-1 break-all font-mono text-sm text-[var(--muted-foreground)]">{serverAddress}</p>
                </div>
                <CopyButton text={serverAddress} label="复制地址" />
              </Panel>
              <div className="mt-5 grid gap-3 md:grid-cols-2">
                {client === 'mobile' && (
                  <>
                    <GuideCard tone="claret" icon={<Smartphone size={16} />} title="Android" steps={['安装 EchoShelf。', '添加上方服务器地址。', '输入账号和密码登录。']} action={androidDownloadUrl ? <a className="btn btn-primary mt-4 w-full" href={androidDownloadUrl} target="_blank" rel="noreferrer"><Download size={15} /> 下载 Android 安装包</a> : undefined} />
                    <GuideCard tone="sage" icon={<Smartphone size={16} />} title="iPhone / iPad" steps={[iosGuideText, '添加上方服务器地址。', '输入账号和密码登录。']} />
                  </>
                )}
                {client === 'desktop' && (
                  <>
                    <GuideCard icon={<Monitor size={16} />} title="电脑端" steps={[desktopGuideText]} />
                    <GuideCard icon={<Copy size={16} />} title="登录需要" steps={['账号、密码和上方服务器地址。']} />
                  </>
                )}
                {client === 'notes' && (
                  <>
                    <GuideCard icon={<ShieldCheck size={16} />} title="使用建议" steps={['不要把账号交给他人使用。', '不要公开服务地址。', '到期前可提前兑换续期码。', '遇到登录问题，先检查账号状态。']} />
                    <GuideCard icon={<Headphones size={16} />} title="收听提示" steps={['进度会在登录账号后自动同步。', '更换设备登录后可继续上次进度。', '如有特殊端口或路径，以管理员说明为准。']} />
                  </>
                )}
              </div>
            </Sheet>
          </div>
        )}

        {/* RECORDS */}
        {tab === 'records' && (
          <div className="space-y-5">
            <Sheet className="rounded-[22px] p-6 sm:p-9">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <SectionHeader eyebrow="收听进度" title="收听记录" body="查看作品进度和最近更新时间，方便回到客户端继续收听。" />
                <Button variant="secondary" onClick={loadAll} loading={loading} loadingText="刷新中"><RefreshCcw size={15} /> 刷新</Button>
              </div>
              <div className="mt-7 grid gap-3 md:grid-cols-2">
                {(summary?.progress || []).map((item) => <ProgressCard key={item.id} item={item} />)}
                {!summary?.progress?.length && <Panel className="rounded-[16px] p-5 text-sm text-[var(--muted-foreground)]">当前账号暂无收听记录。开始收听后再回来查看即可。</Panel>}
              </div>
            </Sheet>

            <Sheet className="rounded-[20px] p-6 sm:p-8">
              <SectionHeader eyebrow="媒体内容" title="内容概览" body="查看当前账号可访问的媒体库与收听记录数量。" />
              <div className="mt-6 grid gap-3 sm:grid-cols-2">
                <Stat label="媒体库" value={`${summary?.stats.libraryCount ?? 0} 个`} />
                <Stat label="进度记录" value={`${summary?.stats.progressCount ?? 0} 条`} />
              </div>
              <div className="mt-5 grid gap-3">
                {(summary?.libraries || []).map((item) => (
                  <Panel key={item.id} className="flex items-center gap-3 rounded-[14px] p-4">
                    <Headphones className="shrink-0 text-[var(--primary)]" size={18} />
                    <div className="min-w-0">
                      <p className="font-display font-semibold">{item.name}</p>
                      <p className="mt-1 text-sm text-[var(--muted-foreground)]">类型：{item.mediaType || 'book'} · 最近扫描：{item.lastScan ? formatShanghaiDateTime(item.lastScan) : '未知'}</p>
                    </div>
                  </Panel>
                ))}
              </div>
            </Sheet>
          </div>
        )}
      </div>

      <NavDrawer
        active={tab}
        onSelect={setTab}
        title={siteName}
        subtitle="用户账号中心"
        items={[
          { key: 'account', label: '账号概览', description: '状态、续期与安全设置', icon: <UserRound size={19} /> },
          ...(showRewards ? [{ key: 'rewards' as const, label: '积分权益', description: '签到、兑换与好友邀请', icon: <Gift size={19} /> }] : []),
          ...(showRequests ? [{ key: 'requests' as const, label: '内容请求', description: '求书、播客与处理进度', icon: <BookPlus size={19} />, badge: requests.filter((item) => ['pending', 'accepted'].includes(item.status)).length ? String(requests.filter((item) => ['pending', 'accepted'].includes(item.status)).length) : undefined }] : []),
          { key: 'guide', label: '使用教程', description: '客户端安装与连接指南', icon: <Compass size={19} /> },
          ...(capabilities?.canListen ? [{ key: 'records' as const, label: '收听记录', description: '最近进度与媒体库', icon: <ListMusic size={19} /> }] : []),
        ]}
      />

      {popup && (
        <PromptModal title={popup.title} body={popup.body} onClose={() => setPopup(null)} />
      )}
      {tgUnbindConfirm && (
        <AccessibleModal title="确认解绑 Telegram？" onClose={() => setTgUnbindConfirm(false)} overlayClassName="prompt-overlay" contentClassName="prompt-modal">
          <h2 className="prompt-title">确认解绑 Telegram？</h2>
          <p className="prompt-body">解绑后将停止账号到期、工单和系统通知，也不能再通过 Bot 重置密码。你以后仍可重新绑定。</p>
          <div className="mt-6 flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setTgUnbindConfirm(false)}>取消</Button>
            <Button variant="danger" onClick={() => { setTgUnbindConfirm(false); void unbindTelegram(); }}>确认解绑</Button>
          </div>
        </AccessibleModal>
      )}
    </ShellBackdrop>
  );
}

function Info({ title, value, icon, action }: { title: string; value: string; icon?: ReactNode; action?: ReactNode }) {
  return (
    <Panel className="rounded-[14px] p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-[var(--muted-foreground)]">{icon}{title}</div>
      <div className="mt-2 flex items-start justify-between gap-2">
        <p className="break-words font-display text-lg font-semibold">{value}</p>
        {action}
      </div>
    </Panel>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[rgba(231,246,253,.16)] px-2 py-1 text-xs font-black text-[var(--primary)]"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        } catch {
          setCopied(false);
          window.prompt('浏览器未允许自动复制，请手动复制：', text);
        }
      }}
    >
      <Copy size={12} /> {copied ? '已复制' : label}
    </button>
  );
}

function ClientTab({ active, onClick, icon, title, body }: { active: boolean; onClick: () => void; icon: ReactNode; title: string; body: string }) {
  return (
    <button onClick={onClick} className={`rounded-[16px] border p-4 text-left transition ${active ? 'border-[rgba(0,190,227,.72)] bg-[rgba(0,190,227,.18)] text-[var(--foreground)] shadow-lift' : 'border-[rgba(231,246,253,.22)] bg-[rgba(255,255,255,.09)] text-[var(--foreground)]'}`}>
      <div className="flex items-center gap-2 font-display font-semibold">{icon}{title}</div>
      <p className="mt-2 text-sm text-[var(--muted-foreground)]">{body}</p>
    </button>
  );
}

function GuideCard({ icon, title, steps, tone = 'neutral', action }: { icon: ReactNode; title: string; steps: string[]; tone?: 'claret' | 'sage' | 'neutral'; action?: ReactNode }) {
  const cls = tone === 'sage' ? 'tag-sage' : tone === 'claret' ? 'tag-claret' : 'tag-gold';
  return (
    <Panel className="rounded-[16px] p-5">
      <div className="flex items-center gap-2 font-display font-semibold">
        <span className={`grid size-9 place-items-center rounded-xl ${cls}`}>{icon}</span>{title}
      </div>
      <ol className="mt-4 space-y-3 text-sm leading-6 text-[var(--muted-foreground)]">
        {steps.map((step, i) => (
          <li key={step} className="flex gap-3">
            <span className="font-display font-semibold text-[var(--primary)]">{i + 1}.</span><span>{step}</span>
          </li>
        ))}
      </ol>
      {action}
    </Panel>
  );
}

function ProgressCard({ item }: { item: LibrarySummary['progress'][number] }) {
  return (
    <Panel className="rounded-[16px] p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-display text-lg font-semibold">{item.title || '未命名作品'}</p>
          {(item.author || item.narrator) && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{item.author || '作者未知'}{item.narrator ? ` · ${item.narrator}` : ''}</p>}
        </div>
        <span className="shrink-0 rounded-full tag-claret px-3 py-1 text-sm font-semibold">{item.progressPercent}%</span>
      </div>
      <p className="mt-3 text-sm text-[var(--muted-foreground)]">已听 {item.currentHours} 小时 / 共 {item.durationHours} 小时</p>
      <div className="bar-track mt-3"><div className="bar-fill" style={{ width: `${Math.min(Math.max(item.progressPercent, 0), 100)}%` }} /></div>
      <p className="mt-2 text-xs text-[rgba(166,191,202,.72)]">更新：{item.lastUpdate ? formatShanghaiDateTime(item.lastUpdate) : '未知'}</p>
    </Panel>
  );
}
