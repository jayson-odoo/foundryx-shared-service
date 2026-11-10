/**
 * Plan 19 AC-19-50: the "..." gear is rendered only when at least one form-surface
 * action would actually be offered to this user (permission held AND isVisible).
 * An empty menu must not render a dead gear trigger.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePathname, useSearchParams } from 'next/navigation';
import { ResourceForm } from './resource-form';
import type { ResourceFormConfig } from './types';
import type { ResourceAction } from '@/components/platform/resource-list/types';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/records/rec-1'),
  useSearchParams: vi.fn(),
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

interface Rec {
  id: string;
}

const act = (over: Partial<ResourceAction<Rec>>): ResourceAction<Rec> => ({
  id: 'a',
  label: 'Archive',
  surfaces: { form: true },
  run: vi.fn(),
  ...over,
});

function config(actions: ResourceAction<Rec>[]): ResourceFormConfig<Rec> {
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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePathname).mockReturnValue('/records/rec-1');
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
});

describe('AC-19-50 no empty gear menu', () => {
  it('every form action needs a permission the session lacks -> no gear', () => {
    render(
      <ResourceForm
        config={config([
          act({ id: 'archive', label: 'Archive', permission: 'records.manage' }),
          act({ id: 'restore', label: 'Restore', permission: 'records.manage' }),
        ])}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Actions' })).not.toBeInTheDocument();
  });

  it('every form action is hidden by isVisible -> no gear', () => {
    render(
      <ResourceForm
        config={config([
          act({ id: 'archive', label: 'Archive', isVisible: () => false }),
          act({ id: 'restore', label: 'Restore', isVisible: () => false }),
        ])}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Actions' })).not.toBeInTheDocument();
  });

  it('guard: one visible, permitted action -> the gear renders and opens with it', async () => {
    render(
      <ResourceForm
        config={config([
          act({ id: 'archive', label: 'Archive', permission: 'records.manage' }),
          act({ id: 'dup', label: 'Duplicate' }),
        ])}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }));
    const items = screen.getAllByRole('menuitem').map((i) => i.textContent);
    expect(items).toEqual(['Duplicate']);
  });
});
