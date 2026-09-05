/**
 * AC-DLA-28 (plan 23 D5/D6): the toolbar row is `PageHeader` with exactly one
 * Back (carrying ctx/i/from); the record card shows identity left and
 * RecordActions right in order - pager, gear ("…" ActionMenu, secondary then
 * a separator then destructive last), primary (Edit / Cancel+Save).
 */
import { render, screen, within } from '@testing-library/react';
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

describe('AC-DLA-28 ResourceForm header restructure', () => {
  it('renders exactly one PageHeader-style breadcrumb nav and one Back button on the toolbar row', () => {
    render(<ResourceForm config={baseConfig()} />);
    expect(screen.getAllByRole('navigation', { name: 'breadcrumb' })).toHaveLength(1);
    expect(screen.getAllByRole('link', { name: /back/i })).toHaveLength(1);
  });

  it('Back carries ctx, i and from=<the record id off the URL>', () => {
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams({ ctx: 'CTX', i: '3' }) as unknown as ReturnType<typeof useSearchParams>,
    );
    render(<ResourceForm config={baseConfig()} />);
    const back = screen.getByRole('link', { name: /back/i });
    const url = new URL(back.getAttribute('href')!, 'http://x');
    expect(url.pathname).toBe('/records');
    expect(url.searchParams.get('ctx')).toBe('CTX');
    expect(url.searchParams.get('i')).toBe('3');
    expect(url.searchParams.get('from')).toBe('rec-1');
  });

  it('the record identity is a heading level 2 - PageHeader owns the page\'s one h1', () => {
    render(<ResourceForm config={baseConfig()} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Record One' })).toBeInTheDocument();
    // Exactly one h1 in the whole form (PageHeader's), never a second one
    // from the record identity.
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });

  it('RecordActions gear menu orders secondary first, destructive last with a separator', async () => {
    render(<ResourceForm config={baseConfig()} />);
    const gear = screen.getByRole('button', { name: 'Actions' });
    const { default: userEvent } = await import('@testing-library/user-event');
    await userEvent.click(gear);
    const menu = screen.getByRole('menu');
    const items = within(menu).getAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Duplicate', 'Trash']);
    expect(items[items.length - 1].className).toContain('text-destructive');
    expect(items[0].className).not.toContain('text-destructive');
  });

  it('config.breadcrumb renders as the PageHeader crumb trail, naming the record (fix round 1)', () => {
    render(
      <ResourceForm
        config={baseConfig({
          breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Jane Doe' }],
        })}
      />,
    );
    const nav = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(nav).toHaveTextContent('Dashboard');
    expect(nav).toHaveTextContent('Records');
    expect(nav).toHaveTextContent('Jane Doe');
    // Jane Doe (the record) is the CURRENT page, not the sidebar-derived one.
    expect(screen.getByText('Jane Doe').closest('[aria-current="page"]')).toBeTruthy();
  });

  it('config.entityNoun overrides the sidebar-derived noun on the primary button (AC-DLA-35 fix round 1)', async () => {
    render(<ResourceForm config={baseConfig({ entityNoun: 'task' })} />);
    const { default: userEvent } = await import('@testing-library/user-event');
    await userEvent.click(screen.getByRole('button', { name: /edit/i }));
    expect(screen.getByRole('button', { name: 'Save task' })).toBeInTheDocument();
  });

  it('the primary is Edit when not editing, Cancel+Save while editing', async () => {
    render(<ResourceForm config={baseConfig()} />);
    expect(screen.getByRole('button', { name: /edit/i })).toBeInTheDocument();
    const { default: userEvent } = await import('@testing-library/user-event');
    await userEvent.click(screen.getByRole('button', { name: /edit/i }));
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });

  it('RecordActions cluster wraps under the identity at narrow widths (flex-wrap)', () => {
    render(<ResourceForm config={baseConfig()} />);
    const cluster = document.querySelector('[data-slot="record-actions"]');
    expect(cluster?.className).toContain('flex-wrap');
  });

  it('a form-surface action run() receives rt.backHref carrying the SAME ctx/i/from as the Back link (AC-DLA-30 fix round 1, post-delete nav)', async () => {
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams({ ctx: 'CTX', i: '3' }) as unknown as ReturnType<typeof useSearchParams>,
    );
    const run = vi.fn();
    const trashAction: ResourceAction<Rec> = {
      id: 'trash',
      label: 'Trash',
      tone: 'destructive',
      surfaces: { form: true },
      run,
    };
    render(<ResourceForm config={baseConfig({ actions: [trashAction] })} />);
    const gear = screen.getByRole('button', { name: 'Actions' });
    const { default: userEvent } = await import('@testing-library/user-event');
    await userEvent.click(gear);
    await userEvent.click(screen.getByRole('menuitem', { name: 'Trash' }));
    expect(run).toHaveBeenCalled();
    const rt = run.mock.calls[0][1] as { backHref?: string };
    const backLinkHref = screen.getByRole('link', { name: /back/i }).getAttribute('href');
    expect(rt.backHref).toBe(backLinkHref);
  });

  it('embedded mode renders no PageHeader toolbar row, uses onBack in RecordActions instead', () => {
    const onBack = vi.fn();
    render(<ResourceForm config={baseConfig({ embedded: true, onBack })} />);
    expect(screen.queryByRole('navigation', { name: 'breadcrumb' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
  });
});
