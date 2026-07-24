import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/react';
import { Gift, UserRound } from 'lucide-react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NavDrawer } from '@/components/nav-drawer';

type Tab = 'account' | 'rewards';

function DrawerHarness() {
  const [active, setActive] = useState<Tab>('account');
  return (
    <>
      <main data-nav-drawer-background><button type="button">背景操作</button></main>
      <NavDrawer
      active={active}
      onSelect={setActive}
      title="MoYin.CC"
      subtitle="用户账号中心"
      items={[
        { key: 'account', label: '账号概览', description: '状态与安全设置', icon: <UserRound /> },
        { key: 'rewards', label: '积分权益', description: '签到与兑换', icon: <Gift /> },
      ]}
      />
    </>
  );
}

describe('NavDrawer', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.scrollTo = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
  });

  it('uses the same 1023px compact breakpoint as the drawer CSS', () => {
    const matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() });
    window.matchMedia = matchMedia;

    render(<DrawerHarness />);

    expect(matchMedia).toHaveBeenCalledWith('(max-width: 1023px)');
    expect(document.querySelector('#primary-nav-drawer')).toHaveAttribute('inert');
    expect(document.querySelector('#primary-nav-drawer')).toHaveAttribute('aria-hidden', 'true');
  });

  it('opens and closes as an accessible mobile drawer', async () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() });
    const user = userEvent.setup();
    render(<DrawerHarness />);
    const trigger = screen.getByRole('button', { name: '打开导航菜单' });

    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(document.body).toHaveStyle({ overflow: 'hidden' });
    expect(screen.getByRole('main')).toHaveAttribute('inert');

    const close = screen.getByRole('button', { name: '关闭导航菜单' });
    const collapse = screen.getByRole('button', { name: '收缩导航栏' });
    collapse.focus();
    await user.keyboard('{Tab}');
    expect(close).toHaveFocus();
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(collapse).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
    expect(screen.getByRole('main')).not.toHaveAttribute('inert');
    expect(document.querySelector('#primary-nav-drawer')).toHaveAttribute('inert');
  });

  it('marks the active item and switches sections without leaving the page', async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    expect(screen.getByRole('button', { name: /账号概览/ })).toHaveAttribute('aria-current', 'page');

    await user.click(screen.getByRole('button', { name: /积分权益/ }));

    expect(screen.getByRole('button', { name: /积分权益/ })).toHaveAttribute('aria-current', 'page');
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
  });

  it('persists the desktop collapsed preference', async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    await user.click(screen.getByRole('button', { name: '收缩导航栏' }));

    expect(document.documentElement.dataset.navCollapsed).toBe('true');
    expect(window.localStorage.getItem('moyin-nav-collapsed')).toBe('true');
  });
});
