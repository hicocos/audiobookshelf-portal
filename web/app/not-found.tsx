import { ArrowLeft, Compass } from 'lucide-react';
import Link from 'next/link';
import { Panel, ShellBackdrop, WordMark } from '@/components/ui';

export default function NotFound() {
  return (
    <ShellBackdrop className="grid place-items-center px-4 py-10">
      <Panel className="w-full max-w-lg p-7 text-center sm:p-10">
        <WordMark siteName="MoYin.CC" tagline="安静的声音栖地" small />
        <span className="mx-auto mt-8 grid size-14 place-items-center rounded-2xl bg-[rgba(118,87,232,.11)] text-[#694bd1]">
          <Compass size={26} aria-hidden />
        </span>
        <p className="kicker mt-5 justify-center">404</p>
        <h1 className="display-md mt-3">没有找到这个页面</h1>
        <p className="lede mt-3">链接可能已失效，或者页面已经移动。</p>
        <Link href="/" className="btn btn-primary mt-6 w-full"><ArrowLeft size={16} /> 返回首页</Link>
      </Panel>
    </ShellBackdrop>
  );
}
