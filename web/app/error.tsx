'use client';

import { AlertTriangle, RotateCcw } from 'lucide-react';
import { useEffect } from 'react';
import { Button, Panel, ShellBackdrop, WordMark } from '@/components/ui';

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <ShellBackdrop className="grid place-items-center px-4 py-10">
      <Panel className="w-full max-w-lg p-7 text-center sm:p-10">
        <WordMark siteName="MoYin.CC" tagline="安静的声音栖地" small />
        <span className="mx-auto mt-8 grid size-14 place-items-center rounded-2xl bg-[rgba(255,111,145,.12)] text-[#a52f52]">
          <AlertTriangle size={26} aria-hidden />
        </span>
        <h1 className="display-md mt-5">页面暂时出了点问题</h1>
        <p className="lede mt-3">请稍后重试。如果问题持续出现，请联系管理员。</p>
        <Button className="mt-6 w-full" onClick={reset}><RotateCcw size={16} /> 重新加载</Button>
      </Panel>
    </ShellBackdrop>
  );
}
