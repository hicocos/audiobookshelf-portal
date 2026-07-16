import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { AccessibleModal } from '@/components/accessible-modal';

function ModalHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>打开设置</button>
      {open && (
        <AccessibleModal title="编辑设置" onClose={() => setOpen(false)}>
          <button type="button">第一个操作</button>
          <input aria-label="名称" />
          <button type="button">最后一个操作</button>
        </AccessibleModal>
      )}
    </>
  );
}

describe('AccessibleModal', () => {
  it('exposes dialog semantics, locks scrolling, and restores focus after Escape', async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);
    const trigger = screen.getByRole('button', { name: '打开设置' });

    await user.click(trigger);

    const dialog = screen.getByRole('dialog', { name: '编辑设置' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByRole('button', { name: '第一个操作' })).toHaveFocus();
    expect(document.body).toHaveStyle({ overflow: 'hidden' });

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
  });

  it('traps forward and backward Tab navigation inside the dialog', async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);
    await user.click(screen.getByRole('button', { name: '打开设置' }));

    const first = screen.getByRole('button', { name: '第一个操作' });
    const last = screen.getByRole('button', { name: '最后一个操作' });

    last.focus();
    await user.tab();
    expect(first).toHaveFocus();

    first.focus();
    await user.tab({ shift: true });
    expect(last).toHaveFocus();
  });
});
