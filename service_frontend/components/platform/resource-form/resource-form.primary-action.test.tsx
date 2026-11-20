/**
 * Plan ideation-br-send-to-build D12 (AC-STB-07): the ResourceForm shell's
 * `primaryAction` + `actionsNote` extension. A primary CTA takes Edit's slot in
 * the record-actions row; Edit moves to be the FIRST item of the existing "..."
 * menu. Without `primaryAction` the shell renders exactly as before.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Rocket } from 'lucide-react';
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

describe('AC-STB-07 ResourceForm without primaryAction (regression)', () => {
  it('renders the plain Edit primary and no Edit item in the menu', async () => {
    render(<ResourceForm config={baseConfig()} />);
    expect(within(recordActions()).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }));
    const items = within(screen.getByRole('menu')).getAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Duplicate', 'Trash']);
    expect(document.querySelector('[data-slot="actions-note"]')).toBeNull();
  });
});

describe('AC-STB-07 ResourceForm with primaryAction', () => {
  it('renders the CTA button in place of Edit and fires onRun on click', () => {
    const onRun = vi.fn();
    render(
      <ResourceForm
        config={baseConfig({ primaryAction: { id: 'send', label: 'Send to build', icon: Rocket, onRun } })}
      />,
    );
    const cta = within(recordActions()).getByRole('button', { name: 'Send to build' });
    expect(cta).not.toBeDisabled();
    expect(within(recordActions()).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    fireEvent.click(cta);
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it('puts Edit FIRST in the "..." menu, above the form actions, and it opens edit mode', async () => {
    render(
      <ResourceForm
        config={baseConfig({ primaryAction: { id: 'send', label: 'Send to build', onRun: vi.fn() } })}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }));
    const items = within(screen.getByRole('menu')).getAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Edit', 'Duplicate', 'Trash']);
    await userEvent.click(items[0]);
    // Edit mode: the shell's Cancel button appears and the CTA is gone.
    expect(await screen.findByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send to build' })).not.toBeInTheDocument();
  });

  it('a disabled CTA has the disabled attribute while the "..." menu stays enabled', () => {
    render(
      <ResourceForm
        config={baseConfig({
          primaryAction: { id: 'send', label: 'Send to build', disabled: true, onRun: vi.fn() },
        })}
      />,
    );
    expect(within(recordActions()).getByRole('button', { name: 'Send to build' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Actions' })).not.toBeDisabled();
  });

  it('renders the reason in the actions-note slot under the row', () => {
    render(
      <ResourceForm
        config={baseConfig({
          primaryAction: {
            id: 'send',
            label: 'Send to build',
            disabled: true,
            reason: 'Missing: Success metric',
          },
        })}
      />,
    );
    const note = document.querySelector('[data-slot="actions-note"]');
    expect(note).not.toBeNull();
    expect(note).toHaveTextContent('Missing: Success metric');
  });

  it('renders config.actionsNote in the actions-note slot', () => {
    render(
      <ResourceForm
        config={baseConfig({
          primaryAction: { id: 'send', label: 'sorento-crm #1402', href: 'https://example.com/1402' },
          actionsNote: 'Sent 30 Sep by Aisha',
        })}
      />,
    );
    expect(document.querySelector('[data-slot="actions-note"]')).toHaveTextContent(
      'Sent 30 Sep by Aisha',
    );
  });

  it('an href primaryAction renders a link that opens a new tab with rel noopener', () => {
    render(
      <ResourceForm
        config={baseConfig({
          primaryAction: { id: 'issue', label: 'sorento-crm #1402', href: 'https://example.com/1402' },
        })}
      />,
    );
    const link = within(recordActions()).getByRole('link', { name: /sorento-crm #1402/ });
    expect(link).toHaveAttribute('href', 'https://example.com/1402');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
  });
});
