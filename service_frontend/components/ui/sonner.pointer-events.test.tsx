/**
 * Plan 26 review round 2, blocker 1: a Radix `Dialog` is modal and sets
 * `document.body.style.pointerEvents = "none"` on its dismissable layer
 * while open. Sonner's toast is a portal appended to `document.body`, so
 * without an explicit opt-out its own CSS inherits `pointer-events: none`
 * too - a countdown toast's Cancel button becomes unclickable while ANY
 * modal dialog is open anywhere on the page (`manage-segments-dialog.tsx`
 * hit exactly this: the countdown toast rendered over the still-open
 * "Manage segments" dialog).
 *
 * Fixed globally in `sonner.tsx` (`pointer-events-auto` on every toast) -
 * this exercises the real `Toaster` + real `sonner` `toast.custom`, with
 * `@testing-library/user-event`'s built-in pointer-events check (v14
 * refuses to dispatch a click through an ancestor with `pointer-events:
 * none` unless the target itself opts back in) standing in for the browser
 * enforcing the CSS. Vitest/jsdom never loads the compiled Tailwind
 * stylesheet, so a bare `<style>` tag defining JUST the one utility class
 * under test (`pointer-events-auto`) stands in for it here - test-only, not
 * a product file, so it does not trip the "no raw CSS in components" rule.
 */
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { toast } from 'sonner';
import { Toaster } from './sonner';

afterEach(() => {
  document.body.style.pointerEvents = '';
});

describe('Toaster pointer-events over a modal (plan 26 review round 2, blocker 1)', () => {
  it('a toast button stays clickable while document.body carries pointer-events: none (modal Dialog open)', async () => {
    const onCancel = vi.fn();
    render(
      <>
        <style>{'.pointer-events-auto { pointer-events: auto; }'}</style>
        <Toaster />
      </>,
    );

    act(() => {
      toast.custom(() => <button onClick={onCancel}>Cancel</button>, { id: 'blocker-1-toast' });
    });
    const button = await screen.findByRole('button', { name: 'Cancel' });

    // Mirrors Radix `DismissableLayer` while a modal Dialog is open.
    document.body.style.pointerEvents = 'none';

    const user = userEvent.setup();
    await user.click(button);

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
