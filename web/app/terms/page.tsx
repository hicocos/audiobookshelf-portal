import Link from 'next/link';
import { Panel, ShellBackdrop, WordMark } from '@/components/ui';

export default function TermsPage() {
  return (
    <ShellBackdrop className="px-3 py-6 sm:px-6 sm:py-10">
      <main className="mx-auto w-full max-w-3xl">
        <Link href="/"><WordMark siteName="MoYin.CC" tagline="服务条款" small /></Link>
        <Panel className="mt-6 rounded-[22px] p-6 sm:p-10">
          <h1 className="font-display text-3xl font-semibold">服务条款</h1>
          <p className="mt-3 text-sm text-[var(--muted-foreground)]">生效日期：2026 年 7 月 17 日</p>
          <div className="mt-8 space-y-7 text-sm leading-7 text-[var(--muted-foreground)]">
            <Term title="服务范围">本站提供受邀账号管理、Audiobookshelf 访问入口、续期、Telegram 辅助操作和内容请求。具体书库、客户端和可用功能以账号中心当时展示为准。</Term>
            <Term title="账号责任">账号仅供获授权的本人使用。请妥善保管密码、邀请码、绑定码和重置链接，不得共享、转售、绕过权限、批量抓取、攻击服务或干扰其他用户。</Term>
            <Term title="内容与请求">内容请求不代表一定收录。你提交的标题、说明和链接应当合法且不侵害他人权益。媒体内容的权利归相应权利人所有；本站不授予超出服务访问所需的复制或传播权。</Term>
            <Term title="到期、停用与注销">账号到期后收听权限会暂停，续期后可恢复。存在滥用、安全风险或违反条款时，管理员可限制或停用账号并保留必要证据。注销申请会区分 Portal 资料、媒体服务器账号、备份和依法保留的安全记录。</Term>
            <Term title="可用性与变更">我们会尽力保持服务稳定，但维护、网络、Telegram 或媒体服务器故障可能造成短时不可用。涉及数据用途或用户权利的重大条款变更会在站内公告；继续使用前应查看更新。</Term>
            <Term title="联系与争议">账号、安全、隐私或内容问题请通过首页公布的支持渠道联系管理员。请提供账号名和问题时间，不要发送当前密码或完整重置令牌。</Term>
          </div>
          <div className="mt-8 flex gap-3"><Link className="btn btn-secondary" href="/">返回首页</Link><Link className="btn btn-secondary" href="/privacy">隐私说明</Link></div>
        </Panel>
      </main>
    </ShellBackdrop>
  );
}

function Term({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h2 className="font-display text-xl font-semibold text-[var(--foreground)]">{title}</h2><p className="mt-2">{children}</p></section>;
}
