'use client';

import { ChevronLeft, ChevronRight, Menu, Sparkles, X } from 'lucide-react';
import { ReactNode, useEffect, useRef, useState } from 'react';

export type NavDrawerItem<Key extends string> = {
  key: Key;
  label: string;
  description: string;
  icon: ReactNode;
  badge?: string;
};

export function NavDrawer<Key extends string>({
  active,
  items,
  onSelect,
  title,
  subtitle,
  ariaLabel = '栏目导航',
}: {
  active: Key;
  items: Array<NavDrawerItem<Key>>;
  onSelect: (key: Key) => void;
  title: string;
  subtitle: string;
  ariaLabel?: string;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [compactViewport, setCompactViewport] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const wasMobileOpenRef = useRef(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem('moyin-nav-collapsed') === 'true');
    const query = window.matchMedia('(max-width: 1023px)');
    const syncViewport = () => setCompactViewport(query.matches);
    syncViewport();
    query.addEventListener?.('change', syncViewport);
    return () => query.removeEventListener?.('change', syncViewport);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.navCollapsed = String(collapsed);
    window.localStorage.setItem('moyin-nav-collapsed', String(collapsed));
    return () => { delete document.documentElement.dataset.navCollapsed; };
  }, [collapsed]);

  useEffect(() => {
    const background = Array.from(document.querySelectorAll<HTMLElement>('[data-nav-drawer-background]'));
    if (!mobileOpen) {
      background.forEach((element) => element.removeAttribute('inert'));
      if (wasMobileOpenRef.current) triggerRef.current?.focus();
      wasMobileOpenRef.current = false;
      return;
    }
    wasMobileOpenRef.current = true;
    background.forEach((element) => element.setAttribute('inert', ''));
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusFrame = window.requestAnimationFrame(() => drawerRef.current?.focus());
    const handleDrawerKeys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMobileOpen(false);
        return;
      }
      if (event.key === 'Tab' && drawerRef.current) {
        if (event.shiftKey && document.activeElement === drawerRef.current) {
          event.preventDefault();
          drawerRef.current.querySelector<HTMLElement>('.nav-drawer-mobile-close')?.focus();
          return;
        }
        const focusable = Array.from(
          drawerRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        );
        if (!focusable.length) {
          event.preventDefault();
          drawerRef.current.focus();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === drawerRef.current)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', handleDrawerKeys);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleDrawerKeys);
      background.forEach((element) => element.removeAttribute('inert'));
    };
  }, [mobileOpen]);

  function select(key: Key) {
    onSelect(key);
    setMobileOpen(false);
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="nav-drawer-trigger"
        aria-label="打开导航菜单"
        aria-controls="primary-nav-drawer"
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen(true)}
      >
        <Menu size={20} />
        <span>菜单</span>
      </button>

      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        className={`nav-drawer-overlay ${mobileOpen ? 'is-visible' : ''}`}
        onClick={() => setMobileOpen(false)}
      />

      <aside
        id="primary-nav-drawer"
        ref={drawerRef}
        tabIndex={-1}
        aria-label={ariaLabel}
        role={mobileOpen ? 'dialog' : undefined}
        aria-modal={mobileOpen || undefined}
        inert={compactViewport && !mobileOpen ? true : undefined}
        aria-hidden={compactViewport && !mobileOpen ? true : undefined}
        className={`nav-drawer ${mobileOpen ? 'is-open' : ''}`}
        data-collapsed={collapsed}
      >
        <div className="nav-drawer-glow" aria-hidden="true" />
        <header className="nav-drawer-head">
          <div className="nav-drawer-brand">
            <span className="nav-drawer-mark">M</span>
            <span className="nav-drawer-brand-copy">
              <span className="nav-drawer-title">{title}</span>
              <span className="nav-drawer-subtitle">{subtitle}</span>
            </span>
          </div>
          <button type="button" className="nav-drawer-mobile-close" aria-label="关闭导航菜单" onClick={() => setMobileOpen(false)}><X size={19} /></button>
        </header>

        <div className="nav-drawer-section-label"><Sparkles size={12} /><span>快速切换</span></div>
        <nav className="nav-drawer-items" aria-label={ariaLabel}>
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`nav-drawer-item ${active === item.key ? 'is-active' : ''}`}
              aria-current={active === item.key ? 'page' : undefined}
              title={collapsed ? item.label : undefined}
              onClick={() => select(item.key)}
            >
              <span className="nav-drawer-icon">{item.icon}</span>
              <span className="nav-drawer-item-copy">
                <span className="nav-drawer-item-row"><span className="nav-drawer-item-label">{item.label}</span>{item.badge && <span className="nav-drawer-badge">{item.badge}</span>}</span>
                <span className="nav-drawer-item-description">{item.description}</span>
              </span>
              <ChevronRight className="nav-drawer-item-arrow" size={16} />
            </button>
          ))}
        </nav>

        <footer className="nav-drawer-foot">
          <span className="nav-drawer-status-dot" />
          <span className="nav-drawer-foot-copy">切换栏目不会退出当前会话</span>
        </footer>

        <button
          type="button"
          className="nav-drawer-collapse"
          aria-label={collapsed ? '展开导航栏' : '收缩导航栏'}
          aria-pressed={collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronRight size={17} /> : <ChevronLeft size={17} />}
          <span>{collapsed ? '展开' : '收缩导航'}</span>
        </button>
      </aside>
    </>
  );
}
