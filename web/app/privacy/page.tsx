import Link from 'next/link';
import { ShieldCheck } from 'lucide-react';
import { Panel, ShellBackdrop, WordMark } from '@/components/ui';

export default function PrivacyPage() {
  return (
    <ShellBackdrop className="px-3 py-6 sm:px-6 sm:py-10">
      <main className="mx-auto w-full max-w-3xl">
        <Link href="/"><WordMark siteName="MoYin.CC" tagline="隐私说明" small /></Link>
        <Panel className="mt-6 rounded-[22px] p-6 sm:p-10">
          <div className="flex items-center gap-3"><ShieldCheck className="text-[var(--primary)]" /><h1 className="font-display text-3xl font-semibold">隐私说明</h1></div>
          <p className="mt-3 text-sm text-[var(--muted-foreground)]">生效日期：2026 年 7 月 17 日</p>
          <div className="mt-8 space-y-7 text-sm leading-7 text-[var(--muted-foreground)]">
            <LegalSection title="我们保存什么">账号标识、用户名、可选邮箱、账号状态与有效期；你主动绑定时的 Telegram ID、用户名和绑定时间；邀请码兑换、积分、内容请求、通知状态与必要安全审计；媒体服务器中的书库权限和收听进度；为防滥用而产生的 IP、设备与访问日志。</LegalSection>
            <LegalSection title="为什么使用">用于创建和维护账号、提供收听与续期、同步 Web/Bot/媒体服务器状态、处理内容请求、发送你选择接收的通知、防止滥用、排障和履行安全责任。不会出售个人信息，也不会将数据用于无关广告画像。</LegalSection>
            <LegalSection title="第三方与跨服务">服务依赖 Telegram、Audiobookshelf、站点托管与反向代理。打开外部 Android 下载或欢迎图片时，对方可能收到你的 IP 和浏览器信息。管理端配置的外部链接并非本站控制，访问前请确认来源。</LegalSection>
            <LegalSection title="保留周期">一次性绑定码和密码重置令牌过期后最多 7 天清理；过期交互流程最多 1 天清理；已发送或最终失败的通知记录最多保留 180 天；普通业务资料在账号存续期间保留。安全审计原则上保留最多 2 年，法律、安全争议或备份恢复所需时可能延长。备份中的删除会随备份轮换完成。</LegalSection>
            <LegalSection title="你的选择与权利">账号中心可以解绑 Telegram 并导出门户数据副本。你也可以通过站点公布的支持渠道申请更正、限制处理或注销。注销会说明 Portal 与 Audiobookshelf 的处理范围；法律要求或安全审计需要保留的最小记录会被隔离并限制访问。</LegalSection>
            <LegalSection title="安全与联系">请勿公开密码、绑定码、邀请码或重置链接。发现账号异常请立即改密并联系管理员。隐私申请请使用首页展示的支持渠道，并提供账号名；管理员不应要求你发送现有密码。</LegalSection>
          </div>
          <div className="mt-8 flex gap-3"><Link className="btn btn-secondary" href="/">返回首页</Link><Link className="btn btn-secondary" href="/terms">服务条款</Link></div>
        </Panel>
      </main>
    </ShellBackdrop>
  );
}

function LegalSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h2 className="font-display text-xl font-semibold text-[var(--foreground)]">{title}</h2><p className="mt-2">{children}</p></section>;
}
