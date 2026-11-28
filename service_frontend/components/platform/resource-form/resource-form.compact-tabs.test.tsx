/**
 * Hub connector fix round: `compactTabs` (opt-in) hides the label of an
 * inactive icon tab below 640px; off by default the tab markup is unchanged.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { Info, Users } from 'lucide-react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
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

const secondaryAction: ResourceAction<Rec> = {
  id: 'duplicate',
  label: 'Duplicate',
  surfaces: { form: true },
  run: vi.fn(),
};
const destructiveAction: ResourceAction<Rec> = {
  id: 'trash',
  label: 'Trash',
  tone: 'destructive',
  surfaces: { form: true },
  run: vi.fn(),
};

function baseConfig(overrides: Partial<ResourceFormConfig<Rec>> = {}): ResourceFormConfig<Rec> {
  return {
    breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Record' }],
    backHref: '/records',
    title: 'Record One',
    tabs: [{ id: 'details', label: 'Details', render: () => <div>Details tab</div> }],
    actions: [secondaryAction, destructiveAction],
    actionRows: [{ id: 'rec-1' }],
    editable: true,
    isDirty: false,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePathname).mockReturnValue('/records/rec-1');
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
});

const iconTabs: ResourceFormConfig<Rec>['tabs'] = [
  { id: 'details', label: 'Details', icon: Info, render: () => <div>Details tab</div> },
  { id: 'people', label: 'People', icon: Users, render: () => <div>People tab</div> },
];

describe('ResourceForm compactTabs', () => {
  it('on: the inactive icon tab label is screen-reader only below sm, the active one stays visible', () => {
    render(<ResourceForm config={baseConfig({ tabs: iconTabs, compactTabs: true })} />);
    const details = screen.getByRole('tab', { name: 'Details' });
    const people = screen.getByRole('tab', { name: 'People' });
    expect(details.querySelector('span')?.className ?? '').not.toContain('max-sm:sr-only');
    expect(people.querySelector('span')?.className).toContain('max-sm:sr-only');
    expect(people.getAttribute('title')).toBe('People');
    fireEvent.mouseDown(people);
    fireEvent.click(people);
  });

  it('off (default): labels are plain text with no title', () => {
    render(<ResourceForm config={baseConfig({ tabs: iconTabs })} />);
    const people = screen.getByRole('tab', { name: 'People' });
    expect(people.querySelector('span')).toBeNull();
    expect(people.getAttribute('title')).toBeNull();
  });
});
