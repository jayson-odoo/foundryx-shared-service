/**
 * AC-94-26 (the merged child form offers only Unmerge + Delete) and AC-94-36
 * (the record pager's `fetchAt` order equals the list order) - issue #94,
 * ideation round 2, plan sections 3.5 and 4.3.
 *
 * TEST-FIRST (PRINCIPLES.md): `useIdeaForm` doesn't know about a merged
 * child yet (its action set is unconditional) and wires no `recordNav` at
 * all - both assertions below fail until slice S1 lands.
 */
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { Form } from '@/components/ui/form';
import { describe, expect, it, vi } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import type { Idea, IdeaClusterSuggestions, Product } from '@/types/ideation';
import type { IdeaService } from '@/services/ideation-service';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { useIdeaForm } from './use-idea-form';
import { selectIdeaRows } from '../select-idea-rows';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: ['ideation.business_requirements.read', 'ideation.triage.manage'] } },
    status: 'authenticated',
  }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 0,
  downvotes: 0,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

const products: Product[] = [{ id: 'prod-1', name: 'Sorento CRM', kind: 'software' }];

function fakeService(overrides: Partial<IdeaService> = {}): IdeaService {
  return {
    listProducts: vi.fn().mockResolvedValue(products),
    listIdeas: vi.fn().mockResolvedValue([]),
    getIdea: vi.fn().mockResolvedValue(anIdea()),
    updateIdea: vi.fn().mockResolvedValue(anIdea()),
    createIdea: vi.fn().mockResolvedValue(anIdea()),
    setStatus: vi.fn().mockResolvedValue(anIdea()),
    vote: vi.fn().mockResolvedValue(anIdea()),
    reorderPriority: vi.fn().mockResolvedValue([]),
    suggestClusters: vi.fn().mockResolvedValue({ clusters: [], degraded: false } as IdeaClusterSuggestions),
    remove: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function wrapper(service: IdeaService) {
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <IdeationRuntimeProvider
        runtime={{
          mode: 'operator',
          service,
          paths: {
            listHref: '/ideation/ideas',
            formHref: (id: string) => `/ideation/ideas/${id}`,
            newHref: '/ideation/ideas/new',
          },
        }}
      >
        {children}
      </IdeationRuntimeProvider>
    );
  }
  return Wrapper;
}

describe('useIdeaForm - a merged child offers only Unmerge and Delete (AC-94-26)', () => {
  it('drops Promote/Advance/Archive/Restore/Merge when the loaded idea is a merged child', async () => {
    const child = anIdea({
      id: 'child-1',
      mergedIntoId: 'survivor-1',
      mergedInto: { id: 'survivor-1', ideaNumber: 'IDEA-0012', title: 'Survivor idea' },
    } as Partial<Idea>);
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(child) });
    const { result } = renderHook(() => useIdeaForm('child-1', false), { wrapper: wrapper(service) });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const ids = (result.current.config?.actions ?? []).map((a) => a.id).sort();
    expect(ids).toEqual(['delete', 'unmerge']);
  });
});

describe('useIdeaForm - recordNav fetchAt order equals list order (AC-94-36)', () => {
  it('walks the SAME order the list fetcher would produce', async () => {
    const rows = [anIdea({ id: 'a' }), anIdea({ id: 'b' }), anIdea({ id: 'c' })];
    const service = fakeService({
      getIdea: vi.fn().mockResolvedValue(rows[0]),
      listIdeas: vi.fn().mockResolvedValue(rows),
    });
    const { result } = renderHook(() => useIdeaForm('a', false), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.config?.recordNav).toBeDefined();
    const at1 = await result.current.config!.recordNav!.fetchAt(
      { page: 0, pageSize: 10, search: '', statusView: 'active' } as never,
      1,
    );
    expect(at1.recordId).toBe('b');
    expect(at1.total).toBe(3);
  });

  it('honours the list query sort + filter, not the default net-vote order (AC-15-09)', async () => {
    const all = [
      anIdea({ id: 'hot-late', upvotes: 9, createdAt: '2026-08-03T00:00:00Z', status: 'discussed' } as Partial<Idea>),
      anIdea({ id: 'cold-early', upvotes: 0, createdAt: '2026-08-01T00:00:00Z', status: 'discussed' } as Partial<Idea>),
      anIdea({ id: 'mid', upvotes: 4, createdAt: '2026-08-02T00:00:00Z', status: 'discussed' } as Partial<Idea>),
      anIdea({ id: 'other-status', upvotes: 1, createdAt: '2026-07-01T00:00:00Z' }),
    ];
    const service = fakeService({
      getIdea: vi.fn().mockResolvedValue(all[0]),
      listIdeas: vi.fn().mockResolvedValue(all),
    });
    const { result } = renderHook(() => useIdeaForm('hot-late', false), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const query = {
      page: 0,
      pageSize: 10,
      search: '',
      statusView: 'active',
      sort: { id: 'submitted', desc: false },
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', field: 'status', operator: 'in', value: ['discussed'] }],
      },
    } as never;
    const expected = selectIdeaRows(all, query);
    expect(expected.map((r) => r.id)).toEqual(['cold-early', 'mid', 'hot-late']);
    const nav = result.current.config!.recordNav!;
    expect((await nav.fetchAt(query, 0)).recordId).toBe(expected[0].id);
    expect((await nav.fetchAt(query, 1)).recordId).toBe(expected[1].id);
    expect((await nav.fetchAt(query, 0)).total).toBe(3);
  });

  it('buildHref carries includeTest forward like brFormHref does', async () => {
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams({ includeTest: '1' }) as unknown as ReturnType<typeof useSearchParams>,
    );
    const service = fakeService();
    const { result } = renderHook(() => useIdeaForm('idea-1', false), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.config?.recordNav).toBeDefined();
    const href = result.current.config!.recordNav!.buildHref('idea-2', 'CTX', 1);
    expect(href).toContain('includeTest=1');
    expect(href).toContain('ctx=CTX');
  });
});


// ── Plan 15 (AC-15-12/13/14/24) ─────────────────────────────────────────────────

function embedWrapper(service: IdeaService) {
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <IdeationRuntimeProvider
        runtime={{
          mode: 'embed',
          service,
          paths: {
            listHref: '/embed/ideas',
            formHref: (id: string) => `/embed/ideas/${id}`,
            newHref: '/embed/ideas/new',
          },
        }}
      >
        {children}
      </IdeationRuntimeProvider>
    );
  }
  return Wrapper;
}

type TabDef = { id: string; render: (ctx: { editing: boolean }) => React.ReactNode };

function tabOf(result: { current: ReturnType<typeof useIdeaForm> }, id: string): TabDef {
  const tab = (result.current.config?.tabs as unknown as TabDef[]).find((t) => t.id === id);
  if (!tab) throw new Error(`tab ${id} missing`);
  return tab;
}

describe('useIdeaForm - subtitle is the status pill (AC-15-12)', () => {
  it('renders a StatusBadge with the statusLabel and no product/submitter text', async () => {
    const service = fakeService({
      getIdea: vi.fn().mockResolvedValue(
        anIdea({ statusLabel: 'Discussed', statusColor: 'indigo', submitterName: 'Zed Submitter' } as Partial<Idea>),
      ),
    });
    const { result } = renderHook(() => useIdeaForm('idea-1', false), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const { container } = render(<>{result.current.config!.subtitle}</>);
    expect(screen.getByText('Discussed')).toBeInTheDocument();
    expect(container.textContent).not.toContain('Sorento CRM');
    expect(container.textContent).not.toContain('Zed Submitter');
  });
});

describe('useIdeaForm - Details tab Product row (AC-15-13)', () => {
  it('has no Product row for an existing idea, view or edit', async () => {
    const service = fakeService();
    const { result } = renderHook(() => useIdeaForm('idea-1', false), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    for (const editing of [false, true]) {
      const { unmount } = render(
        <IdeationRuntimeProvider
          runtime={{
            mode: 'operator',
            service,
            paths: { listHref: '/l', formHref: (id: string) => `/l/${id}`, newHref: '/l/new' },
          }}
        >
          <Form {...result.current.form}>{tabOf(result, 'details').render({ editing })}</Form>
        </IdeationRuntimeProvider>,
      );
      expect(screen.queryByText('Product')).not.toBeInTheDocument();
      unmount();
    }
  });

  it('keeps the Product picker on the create form', async () => {
    const service = fakeService();
    const { result } = renderHook(() => useIdeaForm(undefined, true), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    render(
      <IdeationRuntimeProvider
        runtime={{
          mode: 'operator',
          service,
          paths: { listHref: '/l', formHref: (id: string) => `/l/${id}`, newHref: '/l/new' },
        }}
      >
        <Form {...result.current.form}>{tabOf(result, 'details').render({ editing: true })}</Form>
      </IdeationRuntimeProvider>,
    );
    expect(screen.getByText('Product')).toBeInTheDocument();
  });
});

describe('useIdeaForm - Attachments upload wiring (AC-15-14)', () => {
  it('renders the drop area with a bare "No attachments" empty state', async () => {
    const service = fakeService({ uploadAttachment: vi.fn(), fetchAttachment: vi.fn() });
    const { result } = renderHook(() => useIdeaForm('idea-1', false), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    render(<>{tabOf(result, 'attachments').render({ editing: false })}</>);
    expect(screen.getByText('Drop voice notes, images, videos or files')).toBeInTheDocument();
    expect(screen.getByText('No attachments')).toBeInTheDocument();
    expect(screen.queryByText(/will appear here/i)).not.toBeInTheDocument();
  });

  it('uploading a File calls service.uploadAttachment(ideaId, file) then reloads the idea', async () => {
    const uploaded = { id: 'att-1', kind: 'image', name: 'a.png', url: '', contentPath: '/x' };
    const uploadAttachment = vi.fn().mockResolvedValue(uploaded);
    const getIdea = vi.fn().mockResolvedValue(anIdea());
    const service = fakeService({ uploadAttachment, getIdea });
    const { result } = renderHook(() => useIdeaForm('idea-1', false), { wrapper: wrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const callsBefore = getIdea.mock.calls.length;

    const el = tabOf(result, 'attachments').render({ editing: false }) as ReactElement<{
      onUpload?: (files: File[]) => Promise<void>;
    }>;
    expect(typeof el.props.onUpload).toBe('function');
    const file = new File([new Uint8Array([1, 2, 3])], 'a.png', { type: 'image/png' });
    await act(async () => {
      await el.props.onUpload!([file]);
    });
    expect(uploadAttachment).toHaveBeenCalledWith('idea-1', file);
    expect(getIdea.mock.calls.length).toBeGreaterThan(callsBefore);
  });
});

describe('useIdeaForm - embed promote (AC-15-24)', () => {
  it('shows Promote to BR ungated in embed and runs service.promoteToBr without navigating', async () => {
    const push = vi.fn();
    vi.mocked(useRouter).mockReturnValue({ push, prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
    const promoteToBr = vi.fn().mockResolvedValue({ id: 'br-1', title: 'Order export', brNumber: 'BR-0001' });
    const service = fakeService({ promoteToBr });
    const { result } = renderHook(() => useIdeaForm('idea-1', false), { wrapper: embedWrapper(service) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const promote = result.current.config!.actions.find((a) => a.id === 'promote-br')!;
    expect(promote).toBeDefined();
    expect('permission' in promote ? promote.permission : undefined).toBeUndefined();
    await act(async () => {
      await promote.run?.([anIdea()], { reload: vi.fn() });
    });
    expect(promoteToBr).toHaveBeenCalledWith(['idea-1'], undefined);
    expect(push).not.toHaveBeenCalled();
  });
});
