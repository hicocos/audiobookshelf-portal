'use client';

import Link from 'next/link';
import { CheckCircle2, KeyRound, Lock, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button, ShellBackdrop, StatusNote, WordMark } from '@/components/ui';
import { api } from '@/lib/api';

function ResetPasswordForm() {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [minLength, setMinLength] = useState(8);
  const [message, setMessage] = useState('正在验证一次性链接…');
  const [valid, setValid] = useState(false);
  const [loading, setLoading] = useState(false);
  const [completed, setCompleted] = useState(false);

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const fragmentToken = fragment.get('token') || '';
    window.history.replaceState({}, '', '/reset-password');
    setToken(fragmentToken);
  }, []);

  useEffect(() => {
    let active = true;
    if (token === null) return () => { active = false; };
    if (!token) {
      setMessage('重置链接不完整，请回到 Telegram Bot 重新生成。');
      return () => { active = false; };
    }
    api.validatePasswordReset(token)
      .then((data) => {
        if (!active) return;
        setUsername(data.username);
        setMinLength(data.passwordMinLength);
        setValid(true);
        setMessage('');
      })
      .catch((error) => {
        if (active) setMessage(error instanceof Error ? error.message : '重置链接无效或已过期。');
      });
    return () => { active = false; };
  }, [token]);

  async function submit() {
    if (loading || !valid || !token) return;
    if (password.length < minLength) {
      setMessage(`新密码至少需要 ${minLength} 位。`);
      return;
    }
    if (password !== confirmPassword) {
      setMessage('两次输入的密码不一致。');
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      await api.resetPassword(token, password);
      setCompleted(true);
      setValid(false);
      setPassword('');
      setConfirmPassword('');
      window.history.replaceState({}, '', '/reset-password');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '密码重置失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="anime-panel w-full max-w-xl p-7 sm:p-10">
      <WordMark siteName="MoYin.CC" tagline="账号安全中心" small />
      <div className="mt-9 grid size-12 place-items-center rounded-2xl bg-[rgba(0,190,227,.14)] text-[var(--primary)]">
        {completed ? <CheckCircle2 size={24} /> : <KeyRound size={24} />}
      </div>
      <p className="kicker mt-6">一次性安全链接</p>
      <h1 className="display-md mt-3">{completed ? '密码已重置' : '设置新密码'}</h1>
      <p className="lede mt-3 text-sm">
        {completed
          ? '新密码已同步到听书服务，这个链接已经失效。'
          : username ? `正在为账号 ${username} 重置密码。` : '验证链接后即可设置新密码。'}
      </p>

      {message && <div className="mt-6"><StatusNote tone="danger">{message}</StatusNote></div>}

      {valid && !completed && (
        <>
          <label className="mt-7 block">
            <span className="mb-2 flex items-center gap-2 text-sm font-black"><Lock size={15} /> 新密码</span>
            <input className="field" type="password" autoComplete="new-password" minLength={minLength} maxLength={18} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={`${minLength}–18 位`} />
          </label>
          <label className="mt-4 block">
            <span className="mb-2 flex items-center gap-2 text-sm font-black"><ShieldCheck size={15} /> 确认新密码</span>
            <input className="field" type="password" autoComplete="new-password" maxLength={18} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void submit(); }} placeholder="再次输入新密码" />
          </label>
          <Button className="mt-6 w-full" loading={loading} loadingText="正在同步" onClick={submit}>确认重置密码</Button>
        </>
      )}

      <p className="mt-7 text-center text-sm text-[var(--muted-foreground)]">
        {completed ? '现在可以使用新密码登录。' : '链接过期？请回到 Telegram Bot 重新生成。'}{' '}
        <Link href="/login" className="font-black text-[var(--primary)] underline underline-offset-4">返回登录</Link>
      </p>
    </section>
  );
}

export default function ResetPasswordPage() {
  return (
    <ShellBackdrop className="grid place-items-center px-4 py-8">
      <ResetPasswordForm />
    </ShellBackdrop>
  );
}
