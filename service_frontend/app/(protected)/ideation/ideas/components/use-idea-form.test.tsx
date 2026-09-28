/**
 * AC-94-26 (the merged child form offers only Unmerge + Delete) and AC-94-36
 * (the record pager's `fetchAt` order equals the list order) - issue #94,
 * ideation round 2, plan sections 3.5 and 4.3.
 *
 * TEST-FIRST (PRINCIPLES.md): `useIdeaForm` doesn't know about a merged
 * child yet (its action set is unconditional) and wires no `recordNav` at
 * all - both assertions below fail until slice S1 lands.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useSearchParams } from 'next/navigation';
import type { Idea, IdeaClusterSuggestions, Product } from '@/types/ideation';
import type { IdeaService } from '@/services/ideation-service';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { useIdeaForm } from './use-idea-form';

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
