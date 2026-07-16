'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  CalendarRange, Clock, Compass, Copy, Download, Headphones, KeyRound, LinkIcon, ListMusic, LogOut, Monitor,
  RefreshCcw, ShieldCheck, Smartphone, Ticket, UserRound,
} from 'lucide-react';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { Button, Equalizer, LoadingScreen, Panel, PromptModal, SectionHeader, Sheet, ShellBackdrop, Stat, StatusNote, WordMark, AnnouncementBanner } from '@/components/ui';
import { api, ApiError, clearSession, LibrarySummary, PortalUser, PublicSettings, TelegramBindTokenResponse } from '@/lib/api';

const statusText: Record<string, string> = { active: '正常', expired: '已到期', disabled: '已停用', deleted: '需处理', pending: '待启用' };
const statusHelp: Record<string, string> = {
  active: '账号正常，可以继续在客户端收听。',
  expired: '账号已到期，客户端暂不可听；兑换续期码后会恢复。',
  disabled: '账号被管理员停用，请联系管理员处理。',
  deleted: '账号状态异常，请联系管理员重新确认。',
  pending: '账号待启用，请等待管理员处理。',
};
const roleText: Record<string, string> = { user: '用户', admin: '管理员' };
const fallbackSettings: PublicSettings = {
  siteName: 'MoYin.CC', tagline: '安静的声音栖地', registrationEnabled: true, passwordMinLength: 3,
  copy: { heroKicker: 'AUDIO ISLAND', heroTitle: 'MoYin.CC', heroSubtitle: '安静的声音栖地', primaryCta: '申请访问', secondaryCta: '进入账号中心', notice: '一个轻量、安静、专注的音频内容入口。' },
  links: { libraryUrl: '', supportUrl: '', announcementUrl: '' },
  client: { serverUrl: 'https://listen.moyin.cc', androidDownloadUrl: 'https://mikupan.com/s/AOrU0', iosGuideText: '在 App Store 搜索“EchoShelf”并安装。', desktopGuideText: '暂无稳定方案，建议使用手机或平板。' },
  announcement: { title: '', body: '', linkUrl: '', linkLabel: '', timeline: [] },
  features: { registration: true, showLibraryEntry: false, showSupportEntry: false, showAnnouncements: true },
  operations: { inactivityAutoDisable: false, inactiveDays: 30, newUserGraceDays: 7, lastInactivityCheckAt: null, lastInactivityDisabled: 0 },
  sections: { benefits: [], steps: [], faq: [] },
};
type Tab = 'account' | 'guide' | 'records';
type ClientKey = 'mobile' | 'desktop' | 'notes';

export default function DashboardPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>('account');
  const [client, setClient] = useState<ClientKey>('mobile');
  const [user, setUser] = useState<PortalUser | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [summary, setSummary] = useState<LibrarySummary | null>(null);
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
        api.config().then(setSettings),
        api.me().then((r) => setUser(r.user)),
        api.librarySummary().then(setSummary),
      ]);
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
      if (results[2].status === 'rejected') {
        setMessage((current) => current || '收听数据暂时不可用，可稍后点击刷新。');
      }
    } finally {
      setLoading(false);
      setHasLoaded(true);
    }
  }
  useEffect(() => { void loadAll(); }, []);

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
            : `续期成功，新的有效期至 ${new Date(r.user!.expiresAt!).toLocaleString('zh-CN')}，媒体账号已恢复。`,
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

  const isAdmin = user?.role === 'admin';
  const expiresText = isAdmin ? '管理员长期有效' : user?.expiresAt ? new Date(user.expiresAt).toLocaleString('zh-CN') : '永久有效';
  const daysLeft = isAdmin ? null : user?.expiresAt ? Math.ceil((new Date(user.expiresAt).getTime() - Date.now()) / 86400000) : null;
  const health = user?.status === 'active' ? (daysLeft == null ? 100 : daysLeft > 14 ? 92 : daysLeft > 3 ? 70 : daysLeft > 0 ? 42 : 10) : 18;
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
    <ShellBackdrop className="px-4 pb-28 pt-5 sm:px-6 sm:pt-7 lg:pb-8">
      {loading && !hasLoaded && <LoadingScreen title="正在加载账号中心" subtitle="loading" />}
      {loggingOut && <LoadingScreen title="正在退出" subtitle="see you" />}
      <div className="app-content relative">
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
                  <h1 className="display-lg mt-3 text-[var(--foreground)]">{user?.username || '未登录'}</h1>
                  <p className="mt-4 max-w-xl leading-7 text-[var(--muted-foreground)]">
                    在这里查看账号状态和有效期，也可以续期、配置客户端并管理收听进度。
                  </p>
                </div>
                <div className="account-health-card shrink-0 rounded-[16px] border border-[rgba(231,246,253,.12)] bg-white/5 p-5">
                  <p className="text-xs uppercase tracking-[.2em] text-[rgba(166,191,202,.72)]">账号健康度</p>
                  <p className="mt-1 font-display text-4xl font-semibold text-[var(--foreground)]">{health}</p>
                  <div className="mt-3 h-2 w-44 rounded-full bg-[rgba(26,23,20,.10)]">
                    <div className="h-2 rounded-full bg-gradient-to-r from-[var(--info)] to-[var(--warning)]" style={{ width: `${health}%` }} />
                  </div>
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
              <Sheet className="rounded-[20px] p-6 sm:p-8">
                <SectionHeader eyebrow="账号续期" title="兑换续期码" body="输入管理员发放的续期码，即可延长账号有效期。永久续期码可让账号长期使用。" />
                <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto]">
                  <input className="field font-mono tracking-[.12em]" placeholder="续期码" value={code}
                    onChange={(e) => setCode(e.target.value.toUpperCase())} onKeyDown={(e) => { if (e.key === 'Enter') void redeem(); }} />
                  <Button variant="claret" loading={redeeming} loadingText="兑换中" onClick={redeem}><Ticket size={16} /> 立即续期</Button>
                </div>
              </Sheet>
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
                          绑定时间：{user.telegramBoundAt ? new Date(user.telegramBoundAt).toLocaleString('zh-CN') : '未知'}
                        </p>
                      </div>
                      <Button variant="secondary" loading={tgSaving} loadingText="解绑中" onClick={unbindTelegram}>解绑 Telegram</Button>
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
                        <p className="mt-3 text-xs text-[var(--muted-foreground)]">有效期至：{new Date(tgBindToken.expiresAt).toLocaleString('zh-CN')}</p>
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
                      <p className="mt-1 text-sm text-[var(--muted-foreground)]">类型：{item.mediaType || 'book'} · 最近扫描：{item.lastScan ? new Date(item.lastScan).toLocaleString('zh-CN') : '未知'}</p>
                    </div>
                  </Panel>
                ))}
              </div>
            </Sheet>
          </div>
        )}
      </div>

      <FloatingNav tab={tab} setTab={setTab} />

      {popup && (
        <PromptModal title={popup.title} body={popup.body} onClose={() => setPopup(null)} />
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
      <p className="mt-2 text-xs text-[rgba(166,191,202,.72)]">更新：{item.lastUpdate ? new Date(item.lastUpdate).toLocaleString('zh-CN') : '未知'}</p>
    </Panel>
  );
}

function FloatingNav({ tab, setTab }: { tab: Tab; setTab: (tab: Tab) => void }) {
  const items: Array<{ key: Tab; label: string; icon: ReactNode }> = [
    { key: 'account', label: '账号', icon: <UserRound size={17} /> },
    { key: 'guide', label: '使用教程', icon: <Compass size={17} /> },
    { key: 'records', label: '收听记录', icon: <ListMusic size={17} /> },
  ];
  return (
    <div className="tabbar">
      <div className="side-brand">
        <span className="side-brand-mark">M</span>
        <span><span className="side-brand-title block">MoYin.CC</span><span className="side-brand-sub block">账号中心</span></span>
      </div>
      <p className="side-label">用户中心</p>
      {items.map((item) => (
        <button key={item.key} onClick={() => setTab(item.key)} className={`tab-item ${tab === item.key ? 'tab-item-active' : ''}`}>
          {item.icon}{item.label}
        </button>
      ))}
    </div>
  );
}
