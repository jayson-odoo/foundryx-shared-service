/**
 * Switch-off parity: ConfirmActionDialog (plain and typed), DeferredCountdown
 * and the toast wrapper's output (see parity-utils.ts).
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from '@/lib/toast';
import { Toaster } from '@/components/ui/sonner';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import { DeferredCountdown } from '@/components/platform/resource-actions/deferred-action-button';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import { parityHtml } from './parity-utils';

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

interface Rec {
  id: string;
  slug: string;
}

const rows: Rec[] = [{ id: 't1', slug: 'acme' }];

const plain = {
  id: 'impersonate',
  label: 'Impersonate',
  surfaces: { row: true },
  confirm: {
    title: 'Impersonate this user?',
    description: 'You will act as them.',
  },
  run: vi.fn(),
} as unknown as ResourceAction<Rec>;

const typed = {
  id: 'purge',
  label: 'Purge tenant',
  tone: 'destructive',
  surfaces: { row: true },
  confirm: {
    title: (r: Rec[]) => `Purge ${r[0].slug}?`,
    description: 'This cannot be undone.',
    input: { expected: (r: Rec[]) => r[0].slug },
  },
  run: vi.fn(),
} as unknown as ResourceAction<Rec>;

describe('parity (switch off): ConfirmActionDialog', () => {
  it.each([
    ['plain', plain],
    ['typed', typed],
  ])('%s confirm renders as before', async (_name, action) => {
    render(
      <ConfirmActionDialog
        pending={action}
        rows={rows}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    await screen.findByRole('alertdialog');
    // The lightbox opens on a spring (skipped in tests, but it still lands on
    // a later frame): snapshot only once every animated layer has settled.
    await waitFor(() => {
      for (const el of Array.from(
        document.querySelectorAll<HTMLElement>('[data-slot^="alert-dialog-"]'),
      )) {
        expect(el.style.opacity === '' || el.style.opacity === '1').toBe(true);
      }
    });
    expect(parityHtml(document.body)).toMatchSnapshot();
  });
});

describe('parity (switch off): DeferredCountdown', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'setInterval', 'requestAnimationFrame', 'Date'],
    });
    vi.setSystemTime(new Date('2026-11-18T08:00:00.000Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('single and bulk countdowns render as before', () => {
    const { container } = render(
      <div>
        <DeferredCountdown
          verb="Deleting"
          commitAt="2026-11-18T08:00:10.000Z"
          windowSeconds={10}
          onCancel={vi.fn()}
        />
        <DeferredCountdown
          verb="Deleting"
          commitAt="2026-11-18T08:00:05.000Z"
          windowSeconds={5}
          count={12}
          noun="contacts"
          onCancel={vi.fn()}
        />
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): toast wrapper output', () => {
  it('success, error and info toasts render as before', async () => {
    render(<Toaster />);
    act(() => {
      toast.success('User saved');
      toast.error('Could not save user');
      toast.info('Export started');
    });
    await screen.findByText('Export started');
    // Sonner mounts each toast on a later frame; on a slow runner the newest
    // one can still read data-mounted="false" (and a pre-mount offset) here.
    await waitFor(() => {
      expect(document.querySelectorAll('[data-sonner-toast][data-mounted="true"]')).toHaveLength(3);
    });
    const toaster = document.querySelector('[data-sonner-toaster]');
    expect(toaster).not.toBeNull();
    expect(parityHtml(toaster!.parentElement!)).toMatchSnapshot();
  });
});
