/**
 * Switch-off parity: ResourceForm in read mode and edit mode (see
 * parity-utils.ts).
 */
import type { ReactElement } from 'react';
import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ResourceForm } from '@/components/platform/resource-form/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import { parityHtml } from './parity-utils';

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

interface Rec {
  id: string;
}

const actions: ResourceAction<Rec>[] = [
  {
    id: 'duplicate',
    label: 'Duplicate',
    surfaces: { form: true },
    run: vi.fn(),
  },
  {
    id: 'trash',
    label: 'Trash',
    tone: 'destructive',
    surfaces: { form: true },
    run: vi.fn(),
  },
];

function config(
  overrides: Partial<ResourceFormConfig<Rec>> = {},
): ResourceFormConfig<Rec> {
  return {
    breadcrumb: [
      { label: 'Records', href: '/records' },
      { label: 'Record One' },
    ],
    backHref: '/records',
    title: 'Record One',
    tabs: [
      { id: 'details', label: 'Details', render: () => <div>Details tab</div> },
      {
        id: 'activity',
        label: 'Activity',
        render: () => <div>Activity tab</div>,
      },
    ],
    actions,
    actionRows: [{ id: 'rec-1' }],
    editable: true,
    isDirty: false,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
    ...overrides,
  };
}

/** Renders and lets the async terminology lookup settle before the snapshot. */
async function settle(ui: ReactElement): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    ({ container } = render(ui));
  });
  return container;
}

describe('parity (switch off): ResourceForm', () => {
  it('read mode renders as before', async () => {
    const container = await settle(<ResourceForm config={config()} />);
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('a dirty form in edit mode renders as before', async () => {
    const container = await settle(
      <ResourceForm config={config({ initialEditing: true, isDirty: true })} />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
