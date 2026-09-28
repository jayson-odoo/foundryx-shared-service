/**
 * AC-94-25 (issue #94, ideation round 2) - the survivor form's "Merged from"
 * tab: lists the merged children on the shared `ResourceList` (a clone of
 * `IdeaBrsTab`), each row opening that child's form, with a row and bulk
 * "Unmerge" action (plan section 3.5).
 *
 * TEST-FIRST (PRINCIPLES.md): `./idea-merged-tab` and the
 * `@/hooks/use-idea-merged` hook it reads from don't exist yet - fails with a
 * module-not-found error until slice S1 lands.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import type { Idea } from '@/types/ideation';
import { IdeaMergedTab } from './idea-merged-tab';

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

const useIdeaMerged = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-idea-merged', () => ({
  useIdeaMerged: (...a: unknown[]) => useIdeaMerged(...a),
}));

const child = (over: Partial<Idea> = {}): Idea => ({
  id: 'child-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel (duplicate wording)',
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

describe('IdeaMergedTab (AC-94-25)', () => {
  it('lists the merged children, each row opening that child', async () => {
    useIdeaMerged.mockReturnValue({ merged: [child()] });
    const onUnmerge = vi.fn().mockResolvedValue(undefined);
    render(<IdeaMergedTab ideaId="survivor-1" onUnmerge={onUnmerge} />);

    const table = await screen.findByRole('table');
    expect(within(table).getByText(/Export orders to Excel/i)).toBeInTheDocument();
  });

  it('offers a row Unmerge action that calls onUnmerge([childId])', async () => {
    const user = userEvent.setup();
    useIdeaMerged.mockReturnValue({ merged: [child()] });
    const onUnmerge = vi.fn().mockResolvedValue(undefined);
    render(<IdeaMergedTab ideaId="survivor-1" onUnmerge={onUnmerge} />);

    await screen.findByText(/Export orders to Excel/i);
    const rowMenuButton = screen.getByRole('button', { name: /open row actions|actions/i });
    await user.click(rowMenuButton);
    const unmergeItem = await screen.findByRole('menuitem', { name: /unmerge/i });
    await user.click(unmergeItem);
    await waitFor(() => expect(onUnmerge).toHaveBeenCalledWith(['child-1']));
  });

  it('is empty-state when there are no merged children', async () => {
    useIdeaMerged.mockReturnValue({ merged: [] });
    render(<IdeaMergedTab ideaId="survivor-1" onUnmerge={vi.fn()} />);
    expect(await screen.findByText(/no merged ideas|nothing merged/i)).toBeInTheDocument();
  });
});
