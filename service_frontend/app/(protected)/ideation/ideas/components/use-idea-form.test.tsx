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
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import type { Idea, IdeaClusterSuggestions, Product } from '@/types/ideation';
import type { IdeaService } from '@/services/ideation-service';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { ApiError } from '@/lib/api-client';
import { useIdeaForm } from './use-idea-form';
import { selectIdeaRows } from '../select-idea-rows';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

const DEFAULT_PERMS = ['ideation.business_requirements.read', 'ideation.triage.manage'];
const sessionPerms = vi.hoisted(() => ({
  list: ['ideation.business_requirements.read', 'ideation.triage.manage'] as string[],
}));
// Tests that narrow the session must not leak into the next test.
beforeEach(() => {
  sessionPerms.list = [...DEFAULT_PERMS];
});
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: sessionPerms.list } },
    status: 'authenticated',
  }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

const toastMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
}));
vi.mock('@/lib/toast', () => ({ toast: toastMock }));

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
  it('drops Promote/Advance/Archive/Restore/Merge when the loaded idea is a merged child (Unmerge is the primary)', async () => {
    const child = anIdea({
      id: 'child-1',
      mergedIntoId: 'survivor-1',
      mergedInto: { id: 'survivor-1', ideaNumber: 'IDEA-0012', title: 'Survivor idea' },
    } as Partial<Idea>);
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(child) });
    const { result } = renderHook(() => useIdeaForm('child-1', false), { wrapper: wrapper(service) });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    // Plan 19 (AC-19-19): Unmerge is now the PRIMARY action, so it is removed from
    // the "..." menu (no duplicate); Delete stays.
    const ids = (result.current.config?.actions ?? []).map((a) => a.id).sort();
    expect(ids).toEqual(['delete']);
    expect(result.current.config?.primaryAction?.label).toBe('Unmerge');
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


// ── Plan 19 (AC-19-16/19/20) - header vote box + next-state primary action ──────

const triaged = { id: 'tr-triage', label: 'Triage', toStatusId: 'st-triaged', toStatusLabel: 'Triaged' };
const linked = { id: 'tr-link', label: 'Link', toStatusId: 'st-linked', toStatusLabel: 'Linked to BR' };

function stageIdea(over: Partial<Idea> = {}): Idea {
  return anIdea({
    status: 'captured',
    statusId: 'st-captured',
    statusLabel: 'New',
    statusIsArchived: false,
    transitions: [triaged],
    advanceTransitionId: 'tr-triage',
    ...over,
  } as Partial<Idea>);
}

async function loaded(
  idea: Idea,
  service: IdeaService = fakeService({ getIdea: vi.fn().mockResolvedValue(idea) }),
  w: (s: IdeaService) => ({ children }: { children: React.ReactNode }) => ReactElement = wrapper,
) {
  const hook = renderHook(() => useIdeaForm(idea.id, false), { wrapper: w(service) });
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return { ...hook, service };
}

describe('useIdeaForm - next-state primary action (AC-19-19)', () => {
  it('uses editPlacement beside-primary on the idea page', async () => {
    const { result } = await loaded(stageIdea());
    expect(result.current.config?.editPlacement).toBe('beside-primary');
  });

  it('label comes from the transition target: Draft -> "Move to New"', async () => {
    const draftToNew = { id: 'tr-new', label: 'Submit', toStatusId: 'st-new', toStatusLabel: 'New' };
    const { result } = await loaded(
      stageIdea({ status: 'draft', statusLabel: 'Draft', transitions: [draftToNew], advanceTransitionId: 'tr-new' }),
    );
    expect(result.current.config?.primaryAction?.label).toBe('Move to New');
  });

  it('New -> "Move to Triaged"', async () => {
    const { result } = await loaded(stageIdea());
    expect(result.current.config?.primaryAction?.label).toBe('Move to Triaged');
  });

  it('a tenant-relabelled target shows the tenant label ("Move to Discussed")', async () => {
    const relabelled = { ...triaged, toStatusLabel: 'Discussed' };
    const { result } = await loaded(stageIdea({ transitions: [relabelled] }));
    expect(result.current.config?.primaryAction?.label).toBe('Move to Discussed');
  });

  it('no advance transition (closed/terminal) -> no primary action; Edit stays the primary', async () => {
    const { result } = await loaded(stageIdea({ transitions: [], advanceTransitionId: null }));
    expect(result.current.config?.primaryAction).toBeUndefined();
  });

  it('an archived idea with a restore transition -> "Restore"', async () => {
    const restore = { id: 'tr-restore', label: 'Restore', toStatusId: 'st-captured', toStatusLabel: 'New' };
    const { result } = await loaded(
      stageIdea({ statusIsArchived: true, transitions: [restore], advanceTransitionId: null }),
    );
    expect(result.current.config?.primaryAction?.label).toBe('Restore');
  });

  it('an archived idea with NO restore transition -> no primary action', async () => {
    const { result } = await loaded(
      stageIdea({ statusIsArchived: true, transitions: [], advanceTransitionId: null }),
    );
    expect(result.current.config?.primaryAction).toBeUndefined();
  });

  it('a merged child -> "Unmerge", and clicking it calls service.unmerge(id)', async () => {
    const child = stageIdea({ id: 'child-1', mergedIntoId: 'survivor-1' });
    const unmerge = vi.fn().mockResolvedValue([anIdea({ id: 'child-1' })]);
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(child), unmerge });
    const { result } = await loaded(child, service);
    expect(result.current.config?.primaryAction?.label).toBe('Unmerge');
    await act(async () => {
      await result.current.config!.primaryAction!.onRun?.();
    });
    expect(unmerge).toHaveBeenCalledWith('child-1');
  });

  it('the chosen move is removed from the menu; Promote, Archive, Delete stay', async () => {
    const { result } = await loaded(stageIdea());
    const ids = (result.current.config?.actions ?? []).map((a) => a.id);
    expect(ids).not.toContain('advance');
    expect(ids).toEqual(expect.arrayContaining(['promote-br', 'archive', 'delete']));
  });

  it('Restore is not duplicated in the menu when it is the primary', async () => {
    const restore = { id: 'tr-restore', label: 'Restore', toStatusId: 'st-captured', toStatusLabel: 'New' };
    const { result } = await loaded(
      stageIdea({ statusIsArchived: true, transitions: [restore], advanceTransitionId: null }),
    );
    expect((result.current.config?.actions ?? []).map((a) => a.id)).not.toContain('restore');
  });

  it('embed mode gets the same next-state primary action', async () => {
    const idea = stageIdea();
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(idea) });
    const { result } = await loaded(idea, service, embedWrapper);
    expect(result.current.config?.primaryAction?.label).toBe('Move to Triaged');
    expect(result.current.config?.editPlacement).toBe('beside-primary');
  });
});

describe('useIdeaForm - clicking the primary move (AC-19-20)', () => {
  it('fires setStatus(id, toStatusId), refreshes the idea, toasts "Moved to <label>." and the next primary follows', async () => {
    toastMock.success.mockClear();
    const moved = stageIdea({
      status: 'triaged',
      statusId: 'st-triaged',
      statusLabel: 'Triaged',
      transitions: [linked],
      advanceTransitionId: 'tr-link',
    });
    const setStatus = vi.fn().mockResolvedValue(moved);
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(stageIdea()), setStatus });
    const { result } = await loaded(stageIdea(), service);

    expect(result.current.config?.primaryAction?.label).toBe('Move to Triaged');
    await act(async () => {
      await result.current.config!.primaryAction!.onRun?.();
    });
    expect(setStatus).toHaveBeenCalledWith('idea-1', 'st-triaged');
    expect(toastMock.success).toHaveBeenCalledWith('Moved to Triaged.');
    await waitFor(() =>
      expect(result.current.config?.primaryAction?.label).toBe('Move to Linked to BR'),
    );
  });

  it('Restore fires setStatus(id, restore target) and toasts', async () => {
    toastMock.success.mockClear();
    const restore = { id: 'tr-restore', label: 'Restore', toStatusId: 'st-captured', toStatusLabel: 'New' };
    const archived = stageIdea({ statusIsArchived: true, transitions: [restore], advanceTransitionId: null });
    const setStatus = vi.fn().mockResolvedValue(stageIdea());
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(archived), setStatus });
    const { result } = await loaded(archived, service);
    await act(async () => {
      await result.current.config!.primaryAction!.onRun?.();
    });
    expect(setStatus).toHaveBeenCalledWith('idea-1', 'st-captured');
    expect(toastMock.success).toHaveBeenCalled();
  });
});

describe('useIdeaForm - header vote box in the avatar slot (AC-19-16)', () => {
  it('the avatar is the md vote box (not the lightbulb) and shows the upvote count', async () => {
    const { result } = await loaded(stageIdea({ upvotes: 4 }));
    const { container } = render(<>{result.current.config!.avatar}</>);
    const box = container.querySelector('[data-variant="box"]');
    expect(box).not.toBeNull();
    expect(box?.getAttribute('data-size')).toBe('md');
    expect(screen.getByRole('button', { name: /upvote/i })).toHaveTextContent('4');
    expect(screen.queryByRole('button', { name: /downvote/i })).not.toBeInTheDocument();
  });

  it('clicking it calls service.vote(id, "up") and the box reflects the new tally', async () => {
    const voted = stageIdea({ upvotes: 5, myVote: 'up' });
    const vote = vi.fn().mockResolvedValue(voted);
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(stageIdea({ upvotes: 4 })), vote });
    const { result } = await loaded(stageIdea({ upvotes: 4 }), service);
    const { rerender } = render(<>{result.current.config!.avatar}</>);
    await act(async () => {
      screen.getByRole('button', { name: /upvote/i }).click();
    });
    expect(vote).toHaveBeenCalledWith('idea-1', 'up');
    await waitFor(() => expect(result.current.config?.avatar).toBeDefined());
    rerender(<>{result.current.config!.avatar}</>);
    expect(screen.getByRole('button', { name: /cancel upvote/i })).toHaveTextContent('5');
  });

  it('is disabled on a merged child', async () => {
    const { result } = await loaded(stageIdea({ mergedIntoId: 'survivor-1' }));
    render(<>{result.current.config!.avatar}</>);
    expect(screen.getByRole('button', { name: /upvote/i })).toBeDisabled();
  });
});


// ── Plan 19 fix round 1 (AC-19-39 / AC-19-41) ──────────────────────────────────

describe('useIdeaForm - comment composer gate on the PRODUCTION path (AC-19-39)', () => {
  async function renderDetails(mode: 'operator' | 'embed', perms: string[]) {
    sessionPerms.list = perms;
    const service = fakeService({
      getIdea: vi.fn().mockResolvedValue(stageIdea()),
      listComments: vi.fn().mockResolvedValue([
        {
          id: 'c1', ideaId: 'idea-1', parentId: null, authorName: 'Alice', authorKind: 'user',
          body: 'hello there', isDeleted: false, isMine: false, canEdit: false, canDelete: false,
          createdAt: '2026-10-01T08:00:00Z', editedAt: null,
        },
      ]),
    });
    const w = mode === 'embed' ? embedWrapper(service) : wrapper(service);
    const hook = renderHook(() => useIdeaForm('idea-1', false), { wrapper: w });
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
    const Wrap = w;
    render(
      <Wrap>
        <Form {...hook.result.current.form}>{tabOf(hook.result, 'details').render({ editing: false })}</Form>
      </Wrap>,
    );
    await screen.findByText('hello there');
  }

  it('operator WITHOUT ideation.ideas.comment: no composer, no Reply', async () => {
    await renderDetails('operator', ['ideation.ideas.view']);
    expect(screen.queryByRole('button', { name: 'Comment' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reply' })).not.toBeInTheDocument();
  });

  it('operator WITH ideation.ideas.comment: composer and Reply show', async () => {
    await renderDetails('operator', ['ideation.ideas.view', 'ideation.ideas.comment']);
    expect(screen.getByRole('button', { name: 'Comment' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reply' })).toBeInTheDocument();
  });

  it('embed mode shows the composer without any operator permission', async () => {
    await renderDetails('embed', []);
    expect(screen.getByRole('button', { name: 'Comment' })).toBeInTheDocument();
  });
});

describe('useIdeaForm - primary action failures toast, never reject (AC-19-41)', () => {
  it('Move to X: a 409 from setStatus shows toast.error(message) and onRun resolves', async () => {
    toastMock.error.mockClear();
    const setStatus = vi.fn().mockRejectedValue(new ApiError('Illegal transition.', 409, null, undefined));
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(stageIdea()), setStatus });
    const { result } = await loaded(stageIdea(), service);
    await act(async () => {
      await expect(result.current.config!.primaryAction!.onRun?.()).resolves.not.toThrow();
    });
    expect(toastMock.error).toHaveBeenCalledWith('Illegal transition.');
  });

  it('Restore: a 409 toasts the message and does not reject', async () => {
    toastMock.error.mockClear();
    const restore = { id: 'tr-restore', label: 'Restore', toStatusId: 'st-captured', toStatusLabel: 'New' };
    const archived = stageIdea({ statusIsArchived: true, transitions: [restore], advanceTransitionId: null });
    const setStatus = vi.fn().mockRejectedValue(new ApiError('Not allowed.', 409, null, undefined));
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(archived), setStatus });
    const { result } = await loaded(archived, service);
    await act(async () => {
      await result.current.config!.primaryAction!.onRun?.();
    });
    expect(toastMock.error).toHaveBeenCalledWith('Not allowed.');
  });

  it('Unmerge: a 409 toasts the message and does not reject', async () => {
    toastMock.error.mockClear();
    const child = stageIdea({ id: 'child-1', mergedIntoId: 'survivor-1' });
    const unmerge = vi.fn().mockRejectedValue(new ApiError('Cannot unmerge.', 409, null, undefined));
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(child), unmerge });
    const { result } = await loaded(child, service);
    await act(async () => {
      await result.current.config!.primaryAction!.onRun?.();
    });
    expect(toastMock.error).toHaveBeenCalledWith('Cannot unmerge.');
  });
});

// ── Plan 19 fix round 2 (AC-19-46) - Edit + status primary need ideation.triage.manage ──

describe('useIdeaForm - triage.manage gates Edit and the status primary (AC-19-46)', () => {
  const restore = { id: 'tr-restore', label: 'Restore', toStatusId: 'st-captured', toStatusLabel: 'New' };
  const cases: [string, Idea][] = [
    ['a New idea with an advance edge', stageIdea()],
    ['an archived idea', stageIdea({ statusIsArchived: true, transitions: [restore], advanceTransitionId: null })],
    ['a merged child', stageIdea({ id: 'child-1', mergedIntoId: 'survivor-1' })],
  ];

  it.each(cases)('operator WITHOUT triage.manage: no primaryAction for %s; editPermission is set', async (_n, idea) => {
    sessionPerms.list = ['ideation.ideas.view', 'ideation.ideas.upvote'];
    const { result } = await loaded(idea);
    expect(result.current.config?.primaryAction).toBeUndefined();
    expect(result.current.config?.editPermission).toBe('ideation.triage.manage');
  });

  it.each(cases)('operator WITH triage.manage: primaryAction present for %s', async (_n, idea) => {
    sessionPerms.list = ['ideation.ideas.view', 'ideation.triage.manage'];
    const { result } = await loaded(idea);
    expect(result.current.config?.primaryAction).toBeDefined();
    expect(result.current.config?.editPermission).toBe('ideation.triage.manage');
  });

  it('embed mode keeps the primary regardless of operator permissions', async () => {
    sessionPerms.list = [];
    const idea = stageIdea();
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(idea) });
    const { result } = await loaded(idea, service, embedWrapper);
    expect(result.current.config?.primaryAction?.label).toBe('Move to Triaged');
    // Embed: the token is the boundary, so no operator permission gate on Edit (AC-19-49).
    expect(result.current.config?.editPermission).toBeUndefined();
  });
});

describe('useIdeaForm - menu Archive/Restore are gated like Edit (AC-19-49)', () => {
  const permOf = (r: { current: ReturnType<typeof useIdeaForm> }, id: string) => {
    const a = r.current.config?.actions.find((x) => x.id === id);
    expect(a, `${id} action present`).toBeDefined();
    return (a as { permission?: string }).permission;
  };

  it('operator: archive and restore carry permission ideation.triage.manage', async () => {
    const { result } = await loaded(stageIdea());
    expect(permOf(result, 'archive')).toBe('ideation.triage.manage');
    expect(permOf(result, 'restore')).toBe('ideation.triage.manage');
  });

  it('embed: archive and restore carry no permission', async () => {
    const idea = stageIdea();
    const service = fakeService({ getIdea: vi.fn().mockResolvedValue(idea) });
    const { result } = await loaded(idea, service, embedWrapper);
    expect(permOf(result, 'archive')).toBeUndefined();
    expect(permOf(result, 'restore')).toBeUndefined();
  });
});
