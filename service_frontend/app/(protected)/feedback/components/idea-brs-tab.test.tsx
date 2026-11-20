/**
 * Review fix S8 (issue #90 W3, plan s3.5): the idea's Business Requirements
 * tab shows the SAME TEST badge the BR list/detail use on a test BR's row -
 * an idea and its linked BR share the same test/real lane (the invariant a
 * real idea can never link a test BR and vice versa), so this tab's rows
 * mirror that lane visually too.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import type { BusinessRequirement } from '@/types/business-requirement';
import { IdeaBrsTab } from './idea-brs-tab';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/ideation/ideas/idea-1'),
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

const useIdeaBusinessRequirements = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-idea-business-requirements', () => ({
  useIdeaBusinessRequirements: (...a: unknown[]) => useIdeaBusinessRequirements(...a),
}));

const br = (over: Partial<BusinessRequirement> = {}): BusinessRequirement => ({
  id: 'br-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'draft',
  statusLabel: 'Draft',
  statusColor: 'gray',
  templateKey: 'business_requirement',
  templateVersion: 1,
  title: 'Order export',
  ideaCount: 1,
  createdAt: '2026-07-20T10:00:00Z',
  updatedAt: '2026-07-20T10:00:00Z',
  isTest: false,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
});

describe('IdeaBrsTab - S8 TEST badge on a test BR row', () => {
  it('renders the TEST badge on a test BR row, not on a real one', async () => {
    useIdeaBusinessRequirements.mockReturnValue({
      brs: [
        br({ id: 'br-real', title: 'Real requirement', isTest: false }),
        br({ id: 'br-test', title: 'Test requirement', isTest: true }),
      ],
      loading: false,
    });
    render(<IdeaBrsTab ideaId="idea-1" />);

    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeGreaterThan(1));

    const realRow = screen.getByText('Real requirement').closest('tr')!;
    const testRow = screen.getByText('Test requirement').closest('tr')!;
    expect(within(testRow).getByText('TEST')).toBeInTheDocument();
    expect(within(realRow).queryByText('TEST')).not.toBeInTheDocument();
  });

  it('renders no TEST badge when every linked BR is real', async () => {
    useIdeaBusinessRequirements.mockReturnValue({
      brs: [br({ id: 'br-real', title: 'Real requirement', isTest: false })],
      loading: false,
    });
    render(<IdeaBrsTab ideaId="idea-1" />);
    await screen.findByText('Real requirement');
    expect(screen.queryByText('TEST')).not.toBeInTheDocument();
  });
});
