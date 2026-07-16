'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, KeyRound, LifeBuoy, Lock, Sparkles, User } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button, LoadingScreen, ShellBackdrop, StatusNote, WordMark } from '@/components/ui';
import { api, PublicSettings } from '@/lib/api';

export default function RegisterPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [entering, setEntering] = useState(false);
  useEffect(() => { api.config().then(setSettings).catch(() => null); }, []);
  async function submit() {
    if (loading) return;
    if (!registrationEnabled) { setMessage('当前暂未开放自助注册，请联系管理员。'); return; }
    if (!username.trim() || !password || !inviteCode.trim()) { setMessage('请完整填写用户名、密码和邀请码。'); return; }
    if (password.length < minPasswordLength) { setMessage(`密码至少需要 ${minPasswordLength} 位。`); return; }
    setMessage(''); setLoading(true);
    try { await api.register(username.trim(), password, inviteCode.trim()); setEntering(true); setTimeout(() => router.push('/dashboard'), 520); }
    catch (err) { setMessage(err instanceof Error ? err.message : '注册失败'); setLoading(false); }
  }
  const siteName = settings?.siteName || 'MoYin.CC';
  const tagline = settings?.tagline || '安静的声音栖地';
  const registrationEnabled = settings?.features?.registration !== false;
  const minPasswordLength = settings?.passwordMinLength ?? 3;
  const supportUrl = settings?.features?.showSupportEntry ? settings?.links?.supportUrl?.trim() : '';
  const notes = ['用户名建议使用英文、数字或下划线。', '邀请码仅限本人使用，请妥善保存。', '注册成功后可选择 EchoShelf 或其他兼容客户端。'];
  return (
    <ShellBackdrop className="grid place-items-center px-4 py-8">
      {entering && <LoadingScreen title="正在创建账号" subtitle="preparing" />}
      <section className="anime-panel grid w-full max-w-5xl overflow-hidden lg:grid-cols-[.96fr_1.04fr]">
        <div className="relative hidden min-h-[620px] flex-col justify-between p-10 lg:flex">
          <WordMark siteName={siteName} tagline="邀请注册" small />
          <div className="relative z-10">
            <p className="kicker">邀请注册</p>
            <h1 className="display-md mt-4">创建声音账号</h1>
            <p className="lede mt-5 max-w-sm">使用管理员发放的邀请码开通访问。注册完成后，即可查看有效期、续期方式和客户端设置教程。</p>
          </div>
          <div className="space-y-3">{notes.map((text, i) => <div key={text} className="rounded-2xl bg-white/5 p-4"><span className="mr-3 inline-grid size-7 place-items-center rounded-xl bg-[var(--primary)] text-xs font-black text-[var(--primary-foreground)]">{i + 1}</span><span className="text-sm text-[var(--muted-foreground)]">{text}</span></div>)}</div>
        </div>
        <div className="p-7 sm:p-11">
          <div className="lg:hidden"><WordMark siteName={siteName} tagline={tagline} small /></div>
          <p className="kicker mt-8 lg:mt-0">创建账号</p>
          <h2 className="display-md mt-3">受邀注册</h2>
          <p className="lede mt-3 text-sm">填写账号信息和邀请码，即可开通访问。</p>
          {message && <div className="mt-5"><StatusNote tone="danger">{message}</StatusNote>{supportUrl && <a href={supportUrl} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-sm font-black text-[var(--primary)] underline underline-offset-4"><LifeBuoy size={14} /> 注册遇到问题？联系管理员</a>}</div>}
          {!registrationEnabled && <div className="mt-5"><StatusNote tone="warning">当前暂未开放自助注册，请联系管理员。</StatusNote>{supportUrl && <a href={supportUrl} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-sm font-black text-[var(--primary)] underline underline-offset-4"><LifeBuoy size={14} /> 联系管理员</a>}</div>}
          <label className="mt-7 block"><span className="mb-2 flex items-center gap-2 text-sm font-black"><User size={15} /> 用户名</span><input className="field" placeholder="例如 moyin_user" value={username} onChange={(e) => setUsername(e.target.value)} disabled={!registrationEnabled || loading} /></label>
          <label className="mt-4 block"><span className="mb-2 flex items-center gap-2 text-sm font-black"><Lock size={15} /> 密码</span><input className="field" type="password" placeholder={`至少 ${minPasswordLength} 位`} minLength={minPasswordLength} value={password} onChange={(e) => setPassword(e.target.value)} disabled={!registrationEnabled || loading} /></label>
          <label className="mt-4 block"><span className="mb-2 flex items-center gap-2 text-sm font-black"><KeyRound size={15} /> 邀请码</span><input className="field font-mono tracking-[.16em]" placeholder="INVITE-CODE" value={inviteCode} onChange={(e) => setInviteCode(e.target.value.toUpperCase())} disabled={!registrationEnabled || loading} onKeyDown={(e) => { if (e.key === 'Enter') void submit(); }} /></label>
          <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto]"><Button variant="primary" className="w-full" loading={loading} loadingText="创建中" onClick={submit} disabled={!registrationEnabled}>创建账号 <ArrowRight size={17} /></Button><Link href="/login" className="btn btn-secondary"><Sparkles size={15} /> 已有账号</Link></div>
          <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">注册后会自动进入账号中心。</p>
        </div>
      </section>
    </ShellBackdrop>
  );
}
