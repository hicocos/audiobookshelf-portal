'use client';

import { CheckCircle2, Loader2, Bell, Megaphone, X, Sparkles } from 'lucide-react';
import { ButtonHTMLAttributes, ReactNode, useEffect, useState } from 'react';
import { AccessibleModal } from '@/components/accessible-modal';

export function ShellBackdrop({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <main className={`anime-shell relative min-h-screen w-full max-w-[100vw] overflow-x-hidden overflow-y-auto text-[var(--foreground)] ${className}`}>
      <div className="paper-grain" />
      <div className="relative z-10">{children}</div>
    </main>
  );
}

export function BrandMark({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand-mark relative ${small ? 'size-9 text-base' : 'size-12 text-xl'}`} aria-hidden>
      M
    </span>
  );
}

export function WordMark({ siteName, tagline, small = false }: { siteName: string; tagline?: string; small?: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-3">
      <BrandMark small={small} />
      <span className="min-w-0">
        <span className="word-title block truncate text-[1.08rem]">{siteName}</span>
        {tagline && <span className="word-sub block truncate text-xs">{tagline}</span>}
      </span>
    </span>
  );
}

export function Sheet({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`sheet ${className}`}>{children}</section>;
}

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`panel ${className}`}>{children}</div>;
}

export function LoadingScreen({ title = '正在进入', subtitle = 'loading' }: { title?: string; subtitle?: string }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[rgba(3,20,42,.78)] backdrop-blur-md">
      <div className="anime-panel w-[min(320px,calc(100vw-2rem))] p-8 text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-[rgba(0,190,227,.14)] text-[var(--primary)]">
          <Loader2 size={24} className="animate-spin" />
        </span>
        <p className="mt-5 text-xl font-black text-[var(--foreground)]">{title}</p>
        <p className="mt-1 text-xs font-black uppercase tracking-[.32em] text-[var(--muted-foreground)]">{subtitle}</p>
      </div>
    </div>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean;
  loadingText?: string;
  variant?: 'primary' | 'claret' | 'azure' | 'secondary' | 'ghost' | 'danger';
};

export function Button({ children, loading, loadingText, variant = 'primary', className = '', disabled, ...props }: ButtonProps) {
  return (
    <button {...props} disabled={disabled || loading} className={`btn btn-${variant} ${className}`}>
      {loading ? (
        <><Loader2 size={16} className="animate-spin" /> <span>{loadingText || '处理中'}</span></>
      ) : children}
    </button>
  );
}
export const ActionButton = Button;

export function StatusNote({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'danger' }) {
  return <p className={`note note-${tone}`}>{children}</p>;
}

export function PromptModal({ title, body, onClose, confirmText = '我知道了' }: { title: string; body: ReactNode; onClose: () => void; confirmText?: string }) {
  return (
    <AccessibleModal title={title} onClose={onClose} overlayClassName="prompt-overlay" contentClassName="prompt-modal">
      <div className="prompt-icon"><CheckCircle2 size={24} /></div>
      <button type="button" className="prompt-x" aria-label="关闭" onClick={onClose}><X size={18} /></button>
      <h2 className="prompt-title">{title}</h2>
      <div className="prompt-body">{body}</div>
      <button type="button" className="prompt-btn" onClick={onClose}>{confirmText}</button>
    </AccessibleModal>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <span className="lbl">{label}</span>
      <span className="val">{value}</span>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}
export const Metric = ({ label, value, hint }: { label: string; value: string; hint?: string }) => <Stat label={label} value={value} hint={hint} />;

export function SectionHeader({ eyebrow, title, body }: { eyebrow?: string; title: string; body?: string }) {
  return (
    <div>
      {eyebrow && <p className="kicker"><Sparkles size={13} />{eyebrow}</p>}
      <h2 className="display-md mt-3">{title}</h2>
      {body && <p className="lede mt-3 max-w-2xl">{body}</p>}
    </div>
  );
}

export function Equalizer({ count = 18 }: { count?: number }) {
  const heights = Array.from({ length: count }, (_, i) => 36 + Math.round(48 * Math.abs(Math.sin(i * 1.1))));
  return (
    <div className="equalizer">
      {heights.map((h, i) => <span key={i} style={{ height: `${h}%`, animationDelay: `${(i % 6) * 0.12}s` }} />)}
    </div>
  );
}

export function RuleLabel({ children }: { children: ReactNode }) {
  return <div className="kicker">{children}</div>;
}

type TimelineItem = { date?: string; body?: string };

function safeExternalHref(value?: string): string {
  const raw = (value || '').trim();
  if (!raw) return '';
  if (raw.startsWith('/')) return raw.startsWith('//') ? '' : raw;
  try {
    const parsed = new URL(raw);
    return ['https:', 'http:'].includes(parsed.protocol) ? parsed.toString() : '';
  } catch {
    return '';
  }
}


export function AnnouncementBanner({ show, title, body, linkUrl, linkLabel, timeline }: {
  show?: boolean; title?: string; body?: string; linkUrl?: string; linkLabel?: string; timeline?: TimelineItem[]; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [seen, setSeen] = useState(true);
  const [tab, setTab] = useState<'notice' | 'timeline'>('notice');
  const cleanTitle = (title || '').trim();
  const cleanBody = (body || '').trim();
  const items = (timeline || []).filter((t) => (t?.body || '').trim());
  const hasNotice = Boolean(cleanTitle || cleanBody);
  const hasTimeline = items.length > 0;
  const hasContent = hasNotice || hasTimeline;
  const sig = JSON.stringify({ cleanTitle, cleanBody, linkUrl, items });
  const seenKey = 'moyin.ann.seen';
  const showTabs = hasNotice && hasTimeline;

  useEffect(() => {
    setMounted(true);
    if (!show || !hasContent) return;
    try { setSeen(window.localStorage.getItem(seenKey) === sig); } catch { setSeen(false); }
    setTab(hasNotice ? 'notice' : 'timeline');
  }, [show, hasContent, sig, hasNotice]);

  if (!mounted || !show || !hasContent) return null;
  const href = safeExternalHref(linkUrl);
  const activeTab = hasNotice && hasTimeline ? tab : (hasNotice ? 'notice' : 'timeline');
  const openModal = () => {
    try { window.localStorage.setItem(seenKey, sig); } catch {}
    setSeen(true);
    setTab(hasNotice ? 'notice' : 'timeline');
    setOpen(true);
  };

  const modal = open ? (
    <AccessibleModal title="系统公告" onClose={() => setOpen(false)} overlayClassName="ann-overlay" contentClassName="ann-modal">
      <div className="ann-head">
        <h2 className="ann-title"><Bell size={18} />系统公告</h2>
        <button type="button" className="ann-x" aria-label="关闭" onClick={() => setOpen(false)}><X size={20} /></button>
      </div>
      {showTabs && (
        <div className="ann-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={activeTab === 'notice'} className={`ann-tab ${activeTab === 'notice' ? 'is-active' : ''}`} onClick={() => setTab('notice')}><Bell size={15} /> 通知</button>
          <button type="button" role="tab" aria-selected={activeTab === 'timeline'} className={`ann-tab ${activeTab === 'timeline' ? 'is-active' : ''}`} onClick={() => setTab('timeline')}><Megaphone size={15} /> 时间线</button>
        </div>
      )}
      <div className="ann-content">
        {activeTab === 'notice' ? (
          <div className="ann-notice">
            {cleanTitle && <p className="ann-notice-title">{cleanTitle}</p>}
            {cleanBody && <p className="ann-notice-body">{cleanBody}</p>}
            {href && <a className="ann-notice-link" href={href} target="_blank" rel="noopener noreferrer">{linkLabel?.trim() || '查看详情'}</a>}
          </div>
        ) : (
          <ul className="ann-timeline">
            {items.map((it, i) => (
              <li className="ann-tl-item" key={i}>
                <span className="ann-tl-node" />
                <div className="ann-tl-main">
                  <p className="ann-tl-body">{(it.body || '').trim()}</p>
                  {(it.date || '').trim() && <p className="ann-tl-date">{(it.date || '').trim()}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="ann-actions"><button type="button" className="ann-btn ann-btn-primary" onClick={() => setOpen(false)}>关闭</button></div>
    </AccessibleModal>
  ) : null;

  return (
    <>
      <button type="button" className="ann-bell" aria-label="系统公告" onClick={openModal}>
        <Bell size={18} aria-hidden />{!seen && <span className="ann-bell-dot" aria-hidden />}
      </button>
      {modal}
    </>
  );
}

export const Card = Sheet;
export const SoftPanel = Panel;
