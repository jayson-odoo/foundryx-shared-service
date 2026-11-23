/**
 * Switch-off parity for the shells slice F2 branches that F1's harness did not
 * already pin (see parity-utils.ts): an open Tooltip, the shared
 * ConfirmDismissDialog, ResourceForm's own discard dialog, and the
 * deferred-action countdown as the row/bulk toast renders it. Recorded on the
 * code before any F2 change.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Toaster } from '@/components/ui/sonner';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { ConfirmDismissDialog } from '@/components/common/confirm-dismiss-dialog';
import { ResourceForm } from '@/components/platform/resource-form/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { deferredToast } from '@/components/platform/resource-actions/deferred-toast';
import { parityHtml as baseParityHtml } from './parity-utils';

/**
 * React 19's `_r_N_` ids are renamed too, so test order cannot shift them, and
 * a countdown's measured transition time (milliseconds left when its frame
 * ran) is masked: it is timing, not markup.
 */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/transition-duration: \d+ms/g, 'transition-duration: <ms>');
}

/** One element's own markup (outerHTML), normalised like the rest. */
function parityOuter(el: Element): string {
  const holder = document.createElement('div');
  holder.appendChild(el.cloneNode(true));
  return parityHtml(holder);
}

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/records/rec-1'),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: [] } },
    status: 'authenticated',
  }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

/** Waits until every animated alert-dialog layer has landed. */
async function dialogSettled(): Promise<void> {
  await screen.findByRole('alertdialog');
  await waitFor(() => {
    for (const el of Array.from(
      document.querySelectorAll<HTMLElement>('[data-slot^="alert-dialog-"]'),
    )) {
      expect(el.style.opacity === '' || el.style.opacity === '1').toBe(true);
    }
  });
}

describe('parity (switch off): Tooltip', () => {
  it('an open tooltip renders as before', async () => {
    render(
      <TooltipProvider>
        <Tooltip open>
          <TooltipTrigger>Export</TooltipTrigger>
          <TooltipContent>Export users as CSV</TooltipContent>
        </Tooltip>
        <Tooltip open>
          <TooltipTrigger>Help</TooltipTrigger>
          <TooltipContent variant="light" side="bottom">
            Light tooltip
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    await screen.findAllByText('Export users as CSV');
    expect(parityHtml(document.body)).toMatchSnapshot();
  });

  it('the app-wide provider adds no markup', () => {
    const { container } = render(
      <TooltipsProvider>
        <span>child</span>
      </TooltipsProvider>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): ConfirmDismissDialog', () => {
  it('the open dialog renders as before', async () => {
    render(
      <ConfirmDismissDialog
        open
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    await dialogSettled();
    expect(parityHtml(document.body)).toMatchSnapshot();
  });
});

interface Rec {
  id: string;
}

function formConfig(): ResourceFormConfig<Rec> {
  return {
    breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Record One' }],
    backHref: '/records',
    title: 'Record One',
    tabs: [
      { id: 'details', label: 'Details', render: () => <div>Details tab</div> },
    ],
    actions: [],
    actionRows: [{ id: 'rec-1' }],
    editable: true,
    isDirty: true,
    initialEditing: true,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
  };
}

async function settle(ui: ReactElement): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    ({ container } = render(ui));
  });
  return container;
}

describe('parity (switch off): ResourceForm discard dialog', () => {
  it('cancelling a dirty edit opens the dialog as before', async () => {
    await settle(<ResourceForm config={formConfig()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await dialogSettled();
    // The dialog itself: the form behind it carries Radix presence timing.
    expect(parityOuter(screen.getByRole('alertdialog'))).toMatchSnapshot();
  });
});

describe('parity (switch off): deferred-action toast', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'setInterval', 'requestAnimationFrame', 'Date'],
    });
    vi.setSystemTime(new Date('2026-11-18T08:00:00.000Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('the bulk countdown toast renders as before', () => {
    render(<Toaster />);
    act(() => {
      deferredToast({
        id: 'pending-action-bulk-1',
        verb: 'Deleting',
        commitAt: '2026-11-18T08:00:10.000Z',
        windowSeconds: 10,
        count: 12,
        noun: 'contacts',
        onCancel: vi.fn(),
      });
    });
    act(() => {
      vi.advanceTimersByTime(50);
    });
    const countdown = document.querySelector('[data-testid="deferred-countdown"]');
    expect(countdown).not.toBeNull();
    expect(parityHtml(countdown!.parentElement!)).toMatchSnapshot();
  });
});
