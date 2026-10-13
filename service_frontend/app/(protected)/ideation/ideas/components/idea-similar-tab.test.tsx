/**
 * Plan 20 AC-20-23 - the Similar ideas tab: AI-ranked ideas on the shared
 * ResourceList (clone of the Merged-from tab), row/bulk Merge, Retry when the
 * AI is unavailable.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import type { Idea } from '@/types/ideation';
import { IdeaSimilarTab } from './idea-similar-tab';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/ideation/ideas/survivor-1'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/preferences-service', () => ({
  preferencesService: {
    get: vi.fn().mockResolvedValue(null),
    save: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

const useIdeaSimilar = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-idea-similar', () => ({
  useIdeaSimilar: (...a: unknown[]) => useIdeaSimilar(...a),
}));

const similar = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-4',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Dealer portal to see my orders',
  ideaNumber: 'IDEA-0004',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 1,
  downvotes: 0,
  myVote: null,
  priority: 3,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
});

const embedRuntime = {
  mode: 'embed' as const,
  service: ideationEmbedService,
  paths: {
    listHref: '/embed/ideas',
    formHref: (id: string) => `/embed/ideas/${id}`,
    newHref: '/embed/ideas/new',
  },
};

describe('IdeaSimilarTab (plan 20, AC-20-23)', () => {
  it('lists the ranked ideas on the shared list, rows opening that idea', async () => {
    useIdeaSimilar.mockReturnValue({ state: { status: 'ready', ideas: [similar()] }, retry: vi.fn() });
    render(
      <IdeationRuntimeProvider runtime={embedRuntime}>
        <IdeaSimilarTab ideaId="idea-10" onMerge={vi.fn()} />
      </IdeationRuntimeProvider>,
    );
    const table = await screen.findByRole('table');
    expect(within(table).getByText('IDEA-0004')).toBeInTheDocument();
    const hrefs = within(table)
      .getAllByRole('link')
      .map((a) => a.getAttribute('href') ?? '');
    expect(hrefs.some((h) => /^\/embed\/ideas\/idea-4/.test(h))).toBe(true);
    expect(hrefs.join(' ')).not.toMatch(/\/ideation\/ideas\//);
  });

  it('row Merge calls onMerge with that row', async () => {
    const user = userEvent.setup();
    const onMerge = vi.fn();
    useIdeaSimilar.mockReturnValue({ state: { status: 'ready', ideas: [similar()] }, retry: vi.fn() });
    render(
      <IdeationRuntimeProvider runtime={embedRuntime}>
        <IdeaSimilarTab ideaId="idea-10" onMerge={onMerge} />
      </IdeationRuntimeProvider>,
    );
    await screen.findByText(/Dealer portal to see my orders/);
    await user.click(screen.getByRole('button', { name: /open row actions|actions/i }));
    await user.click(await screen.findByRole('menuitem', { name: /^merge$/i }));
    await waitFor(() => expect(onMerge).toHaveBeenCalledWith([expect.objectContaining({ id: 'idea-4' })]));
  });

  it('unavailable shows the message and a Retry that re-asks', async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    useIdeaSimilar.mockReturnValue({ state: { status: 'unavailable' }, retry });
    render(<IdeaSimilarTab ideaId="idea-10" onMerge={vi.fn()} />);
    expect(screen.getByText('Similar ideas unavailable')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalled();
  });

  it('empty result says so', () => {
    useIdeaSimilar.mockReturnValue({ state: { status: 'ready', ideas: [] }, retry: vi.fn() });
    render(<IdeaSimilarTab ideaId="idea-10" onMerge={vi.fn()} />);
    expect(screen.getByText('No similar ideas')).toBeInTheDocument();
  });
});
