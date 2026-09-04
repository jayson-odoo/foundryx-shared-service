/**
 * AC-DLA-44: a form-surface `deferred` gear action replaces the record card's
 * PRIMARY area with `DeferredCountdown` (no dialog); Cancel restores the
 * primary button; on commit the page navigates to `backHref` with a success
 * toast.
 */
import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { ResourceForm } from './resource-form';
import type { ResourceFormConfig } from './types';
import type { ResourceAction } from '@/components/platform/resource-list/types';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/records/rec-1'),
  useSearchParams: vi.fn(),
  useRouter: vi.fn(),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (...a: unknown[]) => toastSuccess(...a),
    error: (...a: unknown[]) => toastError(...a),
  },
}));

const park = vi.fn();
const cancelPark = vi.fn();
const current = vi.fn();
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: {
    park: (...a: unknown[]) => park(...a),
    cancel: (...a: unknown[]) => cancelPark(...a),
    current: (...a: unknown[]) => current(...a),
  },
}));

interface Rec {
  id: string;
}

function baseConfig(actions: ResourceAction<Rec>[]): ResourceFormConfig<Rec> {
  return {
    breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Record' }],
    backHref: '/records',
    title: 'Record One',
    tabs: [{ id: 'details', label: 'Details', render: () => <div>Details tab</div> }],
    actions,
    actionRows: [{ id: 'rec-1' }],
    editable: true,
    isDirty: false,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
  };
}

const routerPush = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePathname).mockReturnValue('/records/rec-1');
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
  vi.mocked(useRouter).mockReturnValue({ push: routerPush, prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  current.mockResolvedValue({ pending: null, lastOutcome: null });
});

const trashAction: ResourceAction<Rec> = {
  id: 'trash',
  label: 'Trash',
  tone: 'destructive',
  surfaces: { form: true },
  deferred: { actionKey: 'users.trash', entityType: 'user', window: 'destructive' },
  run: vi.fn(),
};

describe('AC-DLA-44 ResourceForm deferred (grace-window) form-surface action', () => {
  it('clicking the gear action parks it and replaces the primary with a countdown - no dialog', async () => {
    park.mockResolvedValue({
      id: 'pa1',
      commitAt: new Date(Date.now() + 10_000).toISOString(),
      windowSeconds: 10,
    });
    render(<ResourceForm config={baseConfig([trashAction])} />);

    const gear = screen.getByRole('button', { name: 'Actions' });
    const { default: userEvent } = await import('@testing-library/user-event');
    await userEvent.click(gear);
    await act(async () => {
      await userEvent.click(screen.getByRole('menuitem', { name: 'Trash' }));
    });

    expect(park).toHaveBeenCalledWith('users.trash', 'user', 'rec-1', undefined);
    expect(screen.getByRole('timer')).toHaveTextContent('Trashing in 10s');
    // No dialog opened.
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    // The Edit primary button is gone while the countdown is showing.
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
  });

  it('Cancel restores the primary button, does not navigate', async () => {
    park.mockResolvedValue({
      id: 'pa1',
      commitAt: new Date(Date.now() + 10_000).toISOString(),
      windowSeconds: 10,
    });
    cancelPark.mockResolvedValue({ id: 'pa1', status: 'cancelled' });
    render(<ResourceForm config={baseConfig([trashAction])} />);

    const gear = screen.getByRole('button', { name: 'Actions' });
    const { default: userEvent } = await import('@testing-library/user-event');
    await userEvent.click(gear);
    await act(async () => {
      await userEvent.click(screen.getByRole('menuitem', { name: 'Trash' }));
    });
    expect(screen.getByRole('timer')).toBeInTheDocument();

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    });

    expect(cancelPark).toHaveBeenCalledWith('pa1');
    expect(screen.queryByRole('timer')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /edit/i })).toBeInTheDocument();
    expect(routerPush).not.toHaveBeenCalled();
  });

  it('AC-DLA-46 second-tab parity: a countdown already parked (another tab) shows on mount, with the right verb', async () => {
    current.mockResolvedValue({
      pending: {
        id: 'pa2',
        actionKey: 'users.trash',
        commitAt: new Date(Date.now() + 7_000).toISOString(),
        windowSeconds: 10,
        requestedById: 'other-user',
        requestedByName: 'A teammate',
      },
      lastOutcome: null,
    });

    render(<ResourceForm config={baseConfig([trashAction])} />);

    expect(current).toHaveBeenCalledWith('user', 'rec-1');
    // Flush the watch-from-mount effect's async `current()` read, THEN the
    // label-derivation layout effect that reacts to the resulting pending
    // state (fix round 1 item 11 - moved out of the render body).
    await screen.findByText(/Trashing in/);
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
  });
});
