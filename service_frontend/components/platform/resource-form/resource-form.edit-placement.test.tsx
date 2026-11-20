/**
 * Plan 19 AC-19-18: `ResourceForm` opt-in `editPlacement?: 'menu' | 'beside-primary'`.
 * Default ('menu') is today's behaviour (Edit first in the "..." menu when a
 * primaryAction exists). 'beside-primary' renders Edit as an outline button
 * immediately LEFT of the primary button and removes it from the menu.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ArrowRight } from 'lucide-react';
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

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

interface Rec {
  id: string;
}

const archive: ResourceAction<Rec> = {
  id: 'archive',
  label: 'Archive',
  surfaces: { form: true },
  run: vi.fn(),
};

function baseConfig(overrides: Partial<ResourceFormConfig<Rec>> = {}): ResourceFormConfig<Rec> {
  return {
    breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Record' }],
    backHref: '/records',
    title: 'Record One',
    tabs: [{ id: 'details', label: 'Details', render: () => <div>Details tab</div> }],
    actions: [archive],
    actionRows: [{ id: 'rec-1' }],
    editable: true,
    isDirty: false,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
    primaryAction: { id: 'move', label: 'Move to Triaged', icon: ArrowRight, onRun: vi.fn() },
    ...overrides,
  };
}

function recordActions(): HTMLElement {
  const el = document.querySelector('[data-slot="record-actions"]');
  expect(el).not.toBeNull();
  return el as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePathname).mockReturnValue('/records/rec-1');
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
});

describe('AC-19-18 editPlacement = beside-primary', () => {
  it('renders Edit immediately LEFT of the primary button', () => {
    render(<ResourceForm config={baseConfig({ editPlacement: 'beside-primary' })} />);
    const buttons = within(recordActions()).getAllByRole('button');
    const names = buttons.map((b) => b.textContent?.trim());
    const editAt = names.indexOf('Edit');
    const primaryAt = names.indexOf('Move to Triaged');
    expect(editAt).toBeGreaterThanOrEqual(0);
    expect(primaryAt).toBe(editAt + 1);
  });

  it('Edit is NOT in the "..." menu', async () => {
    render(<ResourceForm config={baseConfig({ editPlacement: 'beside-primary' })} />);
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }));
    const items = within(screen.getByRole('menu')).getAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Archive']);
  });

  it('clicking the beside-primary Edit enters edit mode', async () => {
    render(<ResourceForm config={baseConfig({ editPlacement: 'beside-primary' })} />);
    await userEvent.click(within(recordActions()).getByRole('button', { name: 'Edit' }));
    expect(await screen.findByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('without a primaryAction, Edit is the plain primary and no duplicate appears', async () => {
    render(
      <ResourceForm
        config={baseConfig({ editPlacement: 'beside-primary', primaryAction: undefined })}
      />,
    );
    expect(within(recordActions()).getAllByRole('button', { name: 'Edit' })).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }));
    const items = within(screen.getByRole('menu')).getAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Archive']);
  });
});

describe('AC-19-18 editPlacement default is unchanged (regression)', () => {
  it.each([undefined, 'menu' as const])('editPlacement=%s keeps Edit first in the menu', async (placement) => {
    render(<ResourceForm config={baseConfig({ editPlacement: placement })} />);
    expect(within(recordActions()).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }));
    const items = within(screen.getByRole('menu')).getAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Edit', 'Archive']);
  });
});
