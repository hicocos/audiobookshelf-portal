'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, KeyRound, LifeBuoy, Lock, User } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button, LoadingScreen, ShellBackdrop, StatusNote, WordMark } from '@/components/ui';
import { api, PublicSettings } from '@/lib/api';
import { getSafeDashboardRedirect } from '@/lib/navigation';

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [entering, setEntering] = useState(false);
  useEffect(() => { api.config().then(setSettings).catch(() => null); }, []);
  async function submit() {
    if (loading) return;
    if (!username.trim() || !password) { setMessage('请输入用户名和密码。'); return; }
    setMessage(''); setLoading(true);
    try {
      await api.login(username.trim(), password);
      setEntering(true);
      const next = new URLSearchParams(window.location.search).get('next') || '/dashboard';
      const safeNext = getSafeDashboardRedirect(next);
      setTimeout(() => router.push(safeNext), 450);
    } catch (err) { setMessage(err instanceof Error ? err.message : '登录失败'); setLoading(false); }
  }
  const siteName = settings?.siteName || 'MoYin.CC';
  const tagline = settings?.tagline || '安静的声音栖地';
  const supportUrl = settings?.features?.showSupportEntry ? settings?.links?.supportUrl?.trim() : '';
  return (
    <ShellBackdrop className="grid place-items-center px-4 py-8">
      {entering && <LoadingScreen title="正在进入" subtitle="loading" />}
      <section className="anime-panel grid w-full max-w-5xl overflow-hidden lg:grid-cols-[1.04fr_.96fr]">
        <div className="relative hidden min-h-[560px] flex-col justify-between p-10 lg:flex">
          <WordMark siteName={siteName} tagline="账号中心" small />
          <div className="relative z-10">
            <p className="kicker">欢迎回来</p>
            <h1 className="display-md mt-4">继续你的声音旅程</h1>
            <p className="lede mt-5 max-w-sm">登录后可查看账号状态、完成续期、配置客户端，并接着上次的进度继续收听。</p>
          </div>
          <p className="max-w-sm text-sm leading-7 text-[var(--muted-foreground)]">一个账号，集中管理收听所需的全部信息。</p>
        </div>
        <div className="p-7 sm:p-11">
          <div className="lg:hidden"><WordMark siteName={siteName} tagline={tagline} small /></div>
          <p className="kicker mt-8 lg:mt-0">账号登录</p>
          <h2 className="display-md mt-3">登录 {siteName}</h2>
          <p className="lede mt-3 text-sm">输入账号和密码，进入个人中心。</p>
          {message && <div className="mt-5"><StatusNote tone="danger">{message}</StatusNote>{supportUrl && <a href={supportUrl} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-sm font-black text-[var(--primary)] underline underline-offset-4"><LifeBuoy size={14} /> 登录遇到问题？联系管理员</a>}</div>}
          <label className="mt-7 block"><span className="mb-2 flex items-center gap-2 text-sm font-black"><User size={15} /> 用户名</span><input className="field" autoComplete="username" placeholder="输入用户名" value={username} onChange={(e) => setUsername(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void submit(); }} /></label>
          <label className="mt-4 block"><span className="mb-2 flex items-center gap-2 text-sm font-black"><Lock size={15} /> 密码</span><input className="field" autoComplete="current-password" type="password" placeholder="输入密码" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void submit(); }} /></label>
          <Button variant="primary" className="mt-6 w-full" loading={loading} loadingText="正在验证" onClick={submit}>进入账号中心 <ArrowRight size={17} /></Button>
          <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">还没有账号？ <Link className="font-black text-[var(--primary)] underline underline-offset-4" href="/register">申请访问</Link></p>
          <div className="mt-4 flex items-center justify-center gap-2 text-xs text-[var(--muted-foreground)]"><KeyRound size={13} /> 管理员请前往 <Link href="/admin" className="text-[var(--primary)] underline underline-offset-2">管理台</Link></div>
        </div>
      </section>
    </ShellBackdrop>
  );
}
