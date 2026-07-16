'use client';

import { Lock, ScrollText, ShieldCheck, SlidersHorizontal, User } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button, LoadingScreen, Sheet, ShellBackdrop, StatusNote, WordMark } from '@/components/ui';
import { api, clearSession, PublicSettings } from '@/lib/api';

export default function AdminLoginPage() {
  const router = useRouter();
  const [adminUser, setAdminUser] = useState('admin');
  const [adminPass, setAdminPass] = useState('');
  const [siteName, setSiteName] = useState('MoYin.CC');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [entering, setEntering] = useState(false);

  useEffect(() => {
    api.config().then((c: PublicSettings) => setSiteName(c.siteName || 'MoYin.CC')).catch(() => null);
  }, []);

  async function loginAdmin() {
    if (loading) return;
    const username = adminUser.trim();
    if (!username || !adminPass) {
      setMessage('请输入管理员用户名和密码。');
      return;
    }
    setMessage('');
    setLoading(true);
    try {
      const result = await api.login(username, adminPass);
      if (!['admin', 'root'].includes(result.user.role)) {
        await clearSession().catch(() => null);
        setMessage('当前账号不是管理员。');
        setLoading(false);
        return;
      }
      setEntering(true);
      setTimeout(() => router.push('/admin/config'), 450);
    } catch (loginErr) {
      const loginMessage = loginErr instanceof Error ? loginErr.message : '';
      setMessage(loginMessage || '登录失败');
      setLoading(false);
    }
  }

  const features = [
    { icon: <ShieldCheck size={17} />, title: '后台独立鉴权', body: '仅管理员可进入配置页，操作可确认、可回退。' },
    { icon: <SlidersHorizontal size={17} />, title: '自动化巡检', body: '无收听记录禁用策略可视化管理。' },
    { icon: <ScrollText size={17} />, title: '前台文案统一', body: '首页文案、教程步骤与客服入口集中维护。' },
  ];

  return (
    <ShellBackdrop className="grid place-items-center px-5 py-10">
      {entering && <LoadingScreen title="正在进入管理台" subtitle="console" />}
      <section className="grid w-full max-w-5xl overflow-hidden rounded-[24px] sheet lg:grid-cols-[1.05fr_.95fr]">
        <div className="anime-panel relative hidden flex-col justify-between p-10 lg:flex">
          <WordMark siteName={siteName} tagline="管理台" small />
          <div>
            <p className="kicker !text-[var(--primary)]">运营管理</p>
            <h1 className="display-md mt-4 max-w-md text-[var(--foreground)]">清晰、可靠的运营管理台</h1>
            <p className="mt-5 max-w-sm leading-7 text-[var(--muted-foreground)]">
              集中管理卡密、用户活跃度、巡检策略和前台文案。重要操作均需确认，降低误操作风险。
            </p>
          </div>
          <div className="space-y-3">
            {features.map((f) => (
              <div key={f.title} className="flex items-start gap-3 rounded-xl border border-[rgba(244,239,230,.12)] bg-[rgba(244,239,230,.05)] px-4 py-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[rgba(0,190,227,.14)] text-[var(--warning)]">{f.icon}</span>
                <div>
                  <p className="font-display font-semibold text-[var(--foreground)]">{f.title}</p>
                  <p className="mt-0.5 text-sm text-[rgba(244,239,230,.6)]">{f.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-[rgba(255,255,255,.08)] p-8 sm:p-11">
          <div className="lg:hidden"><WordMark siteName={siteName} tagline="管理台" small /></div>
          <p className="kicker mt-8 lg:mt-0">安全登录</p>
          <h2 className="display-md mt-2">管理员登录</h2>
          <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">
            管理员初始化仅能通过服务器端一次性 setup token 完成。这里仅用于登录已存在的管理员账号。
          </p>

          {message && <div className="mt-5"><StatusNote tone="danger">{message}</StatusNote></div>}

          <label className="mt-7 block">
            <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--muted-foreground)]"><User size={15} /> 管理员用户名</span>
            <input className="field" value={adminUser} onChange={(e) => setAdminUser(e.target.value)} placeholder="admin" disabled={loading} />
          </label>
          <label className="mt-4 block">
            <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--muted-foreground)]"><Lock size={15} /> 管理员密码</span>
            <input className="field" type="password" placeholder="输入管理员密码" value={adminPass}
              onChange={(e) => setAdminPass(e.target.value)} disabled={loading} onKeyDown={(e) => { if (e.key === 'Enter') void loginAdmin(); }} />
          </label>

          <Button variant="claret" className="mt-6 w-full" loading={loading} loadingText="正在进入" onClick={loginAdmin}>登录管理台</Button>
        </div>
      </section>
    </ShellBackdrop>
  );
}
