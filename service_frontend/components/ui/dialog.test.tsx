/**
 * T3 fix round 1 finding 8 - `restoreFocusToOpener` (ported from
 * `sorento_crm`'s `dialog.tsx`). This product almost never renders a
 * `DialogTrigger` - a plain button flips `open` state instead (244 files
 * render `<Dialog>`, a handful use `<DialogTrigger>`) - so Radix's own
 * "return focus to the Trigger" never fires and focus fell to `<body>` on
 * close. `DialogContent` now captures whichever element had focus at the
 * moment it mounted and restores it on `onCloseAutoFocus`, unless the
 * caller's own `onCloseAutoFocus` takes over (`event.preventDefault()`).
 *
 * `userEvent` (not bare `fireEvent`) is required here - a real click
 * focuses a button natively, and only `userEvent.click` reproduces that in
 * jsdom; `fireEvent.click` dispatches the click without the browser's
 * click-to-focus activation behaviour, so the opener would never actually
 * be focused for `DialogContent`'s mount-time capture to find.
 */
import * as React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Dialog, DialogClose, DialogContent, DialogTitle } from './dialog';

function PlainButtonDialog({ onCloseAutoFocus }: { onCloseAutoFocus?: (event: Event) => void }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent onCloseAutoFocus={onCloseAutoFocus} showCloseButton={false}>
          <DialogTitle>Confirm</DialogTitle>
          <DialogClose asChild>
            <button type="button">Dismiss</button>
          </DialogClose>
        </DialogContent>
      </Dialog>
    </>
  );
}

describe('DialogContent restores focus to the opener when no DialogTrigger is used', () => {
  it('returns focus to the plain button that opened it, on Escape', async () => {
    const user = userEvent.setup();
    render(<PlainButtonDialog />);
    const opener = screen.getByRole('button', { name: 'Open dialog' });

    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('dialog', { hidden: true })).toBeInTheDocument());

    await user.keyboard('{Escape}');

    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('returns focus to the opener when closed via a DialogClose button', async () => {
    const user = userEvent.setup();
    render(<PlainButtonDialog />);
    const opener = screen.getByRole('button', { name: 'Open dialog' });

    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('dialog', { hidden: true })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Dismiss' }));

    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("does NOT restore focus when the caller's own onCloseAutoFocus takes over", async () => {
    const user = userEvent.setup();
    const custom = vi.fn((event: Event) => event.preventDefault());
    render(<PlainButtonDialog onCloseAutoFocus={custom} />);
    const opener = screen.getByRole('button', { name: 'Open dialog' });

    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('dialog', { hidden: true })).toBeInTheDocument());

    await user.keyboard('{Escape}');

    await waitFor(() => expect(custom).toHaveBeenCalled());
    expect(opener).not.toHaveFocus();
  });

  it('does not throw when the opener has left the DOM by close time', async () => {
    function UnmountingOpener() {
      const [open, setOpen] = React.useState(false);
      const [showOpener, setShowOpener] = React.useState(true);
      return (
        <>
          {showOpener && (
            <button
              type="button"
              onClick={() => {
                setOpen(true);
                setShowOpener(false);
              }}
            >
              Open then vanish
            </button>
          )}
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent showCloseButton={false}>
              <DialogTitle>Confirm</DialogTitle>
              <DialogClose asChild>
                <button type="button">Dismiss</button>
              </DialogClose>
            </DialogContent>
          </Dialog>
        </>
      );
    }
    const user = userEvent.setup();
    render(<UnmountingOpener />);
    await user.click(screen.getByRole('button', { name: 'Open then vanish' }));
    await waitFor(() => expect(screen.getByRole('dialog', { hidden: true })).toBeInTheDocument());

    await expect(user.click(screen.getByRole('button', { name: 'Dismiss' }))).resolves.not.toThrow();
  });
});
