'use client';

import { useEffect } from 'react';

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="zh-CN">
      <body style={{ margin: 0, background: '#f3f8ff', color: '#172033', fontFamily: 'system-ui, sans-serif' }}>
        <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: '1rem' }}>
          <section style={{ width: 'min(28rem, 100%)', borderRadius: '1.25rem', background: '#fff', padding: '2rem', textAlign: 'center', boxShadow: '0 24px 70px rgba(56,91,139,.18)' }}>
            <p style={{ margin: 0, fontWeight: 800 }}>MoYin.CC</p>
            <h1 style={{ margin: '1.5rem 0 .75rem', fontSize: '1.65rem' }}>应用暂时无法显示</h1>
            <p style={{ margin: 0, color: '#68758c', lineHeight: 1.7 }}>请重新加载页面；如果问题持续出现，请联系管理员。</p>
            <button type="button" onClick={reset} style={{ marginTop: '1.5rem', minHeight: '2.75rem', width: '100%', border: 0, borderRadius: '.8rem', background: '#695af0', color: '#fff', fontWeight: 750, cursor: 'pointer' }}>重新加载</button>
          </section>
        </main>
      </body>
    </html>
  );
}
