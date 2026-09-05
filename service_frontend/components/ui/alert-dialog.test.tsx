/**
 * T3 fix round 1 finding 8 - same `restoreFocusToOpener` guard as
 * dialog.tsx, applied to `AlertDialogContent` (see dialog.test.tsx for the
 * full rationale: this product almost never renders a Trigger, so Radix's
 * own return-to-Trigger focus behaviour never fires without it).
 */
import * as React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogTitle } from './alert-dialog';

function PlainButtonAlertDialog() {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Delete row
      </button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogTitle>Are you sure?</AlertDialogTitle>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

describe('AlertDialogContent restores focus to the opener when no AlertDialogTrigger is used', () => {
  it('returns focus to the plain button that opened it, on Escape', async () => {
    const user = userEvent.setup();
    render(<PlainButtonAlertDialog />);
    const opener = screen.getByRole('button', { name: 'Delete row' });

    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('alertdialog', { hidden: true })).toBeInTheDocument());

    await user.keyboard('{Escape}');

    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('returns focus to the opener when closed via Cancel', async () => {
    const user = userEvent.setup();
    render(<PlainButtonAlertDialog />);
    const opener = screen.getByRole('button', { name: 'Delete row' });

    await user.click(opener);
    await waitFor(() => expect(screen.getByRole('alertdialog', { hidden: true })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(opener).toHaveFocus());
  });
});
