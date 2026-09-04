/**
 * T3 fix round 1 finding 8 - same `restoreFocusToOpener` guard as
 * dialog.tsx, applied to `SheetContent` (see dialog.test.tsx for the full
 * rationale: this product almost never renders a Trigger, so Radix's own
 * return-to-Trigger focus behaviour never fires without it).
 */
import * as React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Sheet, SheetClose, SheetContent, SheetTitle } from './sheet';

function PlainButtonSheet() {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open panel
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent close={false}>
          <SheetTitle>Details</SheetTitle>
          <SheetClose asChild>
            <button type="button">Dismiss</button>
          </SheetClose>
        </SheetContent>
      </Sheet>
    </>
  );
}

describe('SheetContent restores focus to the opener when no SheetTrigger is used', () => {
  it('returns focus to the plain button that opened it, on Escape', async () => {
    const user = userEvent.setup();
    render(<PlainButtonSheet />);
    const opener = screen.getByRole('button', { name: 'Open panel' });

    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('dialog', { hidden: true })).toBeInTheDocument());

    await user.keyboard('{Escape}');

    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('returns focus to the opener when closed via a SheetClose button', async () => {
    const user = userEvent.setup();
    render(<PlainButtonSheet />);
    const opener = screen.getByRole('button', { name: 'Open panel' });

    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('dialog', { hidden: true })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Dismiss' }));

    await waitFor(() => expect(opener).toHaveFocus());
  });
});
