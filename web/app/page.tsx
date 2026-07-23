'use client';

import Link from 'next/link';
import { ArrowUpRight, CalendarClock, Headphones, Library, ShieldCheck, Sparkles, TicketCheck, Waves } from 'lucide-react';
import { useEffect, useState } from 'react';
import { AnnouncementBanner, Panel, ShellBackdrop, WordMark } from '@/components/ui';
import { api, DEFAULT_TELEGRAM_SETTINGS, PublicSettings } from '@/lib/api';

const fallback: PublicSettings = {
  siteName: 'MoYin.CC', tagline: '安静的声音栖地', registrationEnabled: true, passwordMinLength: 3,
  copy: { heroKicker: 'AUDIO ISLAND', heroTitle: 'MoYin.CC', heroSubtitle: '安静的声音栖地', primaryCta: '申请访问', secondaryCta: '进入账号中心', notice: '一个轻量、安静、专注的音频内容入口。' },
  links: { libraryUrl: '', supportUrl: '', announcementUrl: '' },
  client: { serverUrl: 'https://listen.moyin.cc', androidDownloadUrl: 'https://mikupan.com/s/AOrU0', iosGuideText: '在 App Store 搜索“EchoShelf”并安装。', desktopGuideText: '暂无稳定方案，建议使用手机或平板。' },
  announcement: { title: '', body: '', linkUrl: '', linkLabel: '', timeline: [] },
  features: { registration: true, showLibraryEntry: false, showSupportEntry: false, showAnnouncements: true },
  operations: { inactivityAutoDisable: false, inactiveDays: 30, newUserGraceDays: 7, lastInactivityCheckAt: null, lastInactivityDisabled: 0 },
  telegram: { ...DEFAULT_TELEGRAM_SETTINGS },
  sections: {
    benefits: [
      { title: '声音内容库', body: '小说、播客、课程和收藏内容集中在一个入口里，随时打开，继续收听。' },
      { title: '连续收听体验', body: '进度记忆、章节浏览、倍速播放和跨设备接续，适合长期沉浸式收听。' },
      { title: '稳定访问体验', body: '账号状态、续期和客户端教程集中处理，减少来回询问与等待。' },
    ],
    steps: ['领取邀请码或账号', '选择 EchoShelf 等兼容客户端', '添加管理员提供的服务地址', '登录后开始你的声音旅程'],
    faq: [
      { q: '必须使用 EchoShelf 吗？', a: 'EchoShelf 是推荐客户端之一；如果管理员提供了其他兼容客户端，也可以按教程使用。' },
      { q: '账号到期怎么办？', a: '在账号中心兑换续期码即可延长有效期，到期账号可在续期后恢复。' },
      { q: '在哪里看收听进度？', a: '登录账号中心后进入「收听记录」，可以查看近期作品的进度摘要。' },
    ],
  },
};

export default function HomePage() {
  const [settings, setSettings] = useState<PublicSettings>(fallback);
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => { api.config().then(setSettings).catch(() => setSettings(fallback)); api.sessionStatus().then((r) => setAuthed(r.authenticated)).catch(() => setAuthed(false)); }, []);

  const benefits = settings.sections?.benefits?.length ? settings.sections.benefits : fallback.sections.benefits;
  const steps = settings.sections?.steps?.length ? settings.sections.steps : fallback.sections.steps;
  const faq = settings.sections?.faq?.length ? settings.sections.faq : fallback.sections.faq;
  const registrationOn = settings.features?.registration !== false;
  const heroTitle = (settings.copy.heroTitle || fallback.copy.heroTitle).trim();
  const heroSubtitle = (settings.copy.heroSubtitle || fallback.copy.heroSubtitle).trim();
  const heroNotice = (settings.copy.notice || fallback.copy.notice).trim();
  const supportUrl = settings.features?.showSupportEntry ? settings.links?.supportUrl?.trim() : '';
  const benefitIcons = [Library, Waves, ShieldCheck];

  return (
    <ShellBackdrop className="px-3 pb-12 pt-3 sm:px-5 sm:pt-5">
      <div className="anime-wrap">
        <nav className="anime-nav">
          <Link href="/" className="min-w-0"><WordMark siteName={settings.siteName} tagline={settings.tagline} small /></Link>
          <div className="anime-nav-actions">
            <AnnouncementBanner show={settings.features?.showAnnouncements} title={settings.announcement?.title} body={settings.announcement?.body} linkUrl={settings.announcement?.linkUrl} linkLabel={settings.announcement?.linkLabel} timeline={settings.announcement?.timeline} />
            <Link href={authed ? '/dashboard' : '/login'} className="btn btn-secondary !min-h-10 !px-4 text-sm">{authed ? '账号中心' : '登录'}</Link>
          </div>
        </nav>

        <section className="py-10 sm:py-14 lg:py-20">
          <div className="relative z-10 max-w-4xl">
            <p className="kicker"><Sparkles size={13} />{settings.copy.heroKicker || fallback.copy.heroKicker}</p>
            <h1 className="display-lg mt-5 max-w-4xl whitespace-pre-line lg:max-w-3xl">{heroTitle}</h1>
            <p className="mt-5 max-w-2xl text-2xl font-black leading-tight text-[var(--foreground)] sm:text-3xl">{heroSubtitle}</p>
            <p className="lede mt-4 max-w-xl">{heroNotice}</p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              {registrationOn && <Link href="/register" className="btn btn-primary w-full sm:w-auto">{settings.copy.primaryCta || '申请访问'} <ArrowUpRight size={17} /></Link>}
              <Link href={authed ? '/dashboard' : '/login?next=/dashboard'} className="btn btn-secondary w-full sm:w-auto">{settings.copy.secondaryCta || '进入账号中心'}</Link>
            </div>
            {supportUrl && <a href={supportUrl} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-2 text-sm font-black text-[var(--primary)] underline underline-offset-4">遇到问题？联系管理员 <ArrowUpRight size={14} /></a>}
          </div>
        </section>

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['声音内容库', Library],
            ['连续收听', Headphones],
            ['自助续期', CalendarClock],
            ['受邀访问', TicketCheck],
          ].map(([label, Icon]) => {
            const I = Icon as typeof Library;
            return <Panel key={label as string} className="portal-mini-card portal-card-glow flex items-center gap-3 p-4"><span className="grid size-10 place-items-center rounded-2xl tag-claret"><I size={18} /></span><span className="font-black">{label as string}</span></Panel>;
          })}
        </section>

        <section className="py-8 lg:py-10">
          <div className="mb-7 max-w-2xl"><p className="kicker"><Sparkles size={13} />体验亮点</p><h2 className="display-md mt-3">从登录到收听，一步到位。</h2><p className="lede mt-3">账号状态、续期、使用教程和收听进度集中展示，每一步都清晰易找。</p></div>
          <div className="grid gap-4 lg:grid-cols-3">
            {benefits.map((item, i) => {
              const Icon = benefitIcons[i % benefitIcons.length];
              return <Panel key={item.title} className="portal-benefit-card portal-card-glow min-h-52 p-6"><span className="grid size-12 place-items-center rounded-2xl tag-claret"><Icon size={22} /></span><h3 className="mt-5 text-xl font-black">{item.title}</h3><p className="lede mt-3 text-sm">{item.body}</p></Panel>;
            })}
          </div>
        </section>

        <section id="faq" className="grid gap-4 pb-10 lg:grid-cols-[.92fr_1.08fr]">
          <Panel className="portal-steps-card portal-card-glow p-6"><h2 className="text-2xl font-black">进入方式</h2><div className="mt-5 grid gap-3">{steps.map((step, i) => <div key={step} className="flex items-center gap-3 rounded-2xl bg-white/5 p-3"><span className="grid size-9 place-items-center rounded-xl bg-[var(--primary)] text-sm font-black text-[var(--primary-foreground)]">{String(i + 1).padStart(2, '0')}</span><p className="font-bold">{step}</p></div>)}</div></Panel>
          <Panel className="portal-faq-card portal-card-glow p-6"><h2 className="text-2xl font-black">常见问题</h2><div className="mt-5 grid gap-3">{faq.map((item) => <article key={item.q} className="rounded-2xl bg-white/5 p-4"><h3 className="font-black">{item.q}</h3><p className="lede mt-2 text-sm">{item.a}</p></article>)}</div></Panel>
        </section>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 py-6 text-xs text-[var(--muted-foreground)]">
          <p>使用服务即表示你了解本站的数据处理与账号规则。</p>
          <div className="flex gap-4"><Link href="/privacy" className="underline underline-offset-4">隐私说明</Link><Link href="/terms" className="underline underline-offset-4">服务条款</Link></div>
        </footer>
      </div>
    </ShellBackdrop>
  );
}
