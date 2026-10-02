/**
 * AC-94-58 (issue #94, ideation round 2) - S6 live-evidence regression
 * (`documentation/plans/ideation/94-evidence/s6/README.md`, "Known FAIL"):
 * the Triage board crashed in a real browser with `TypeError: Cannot read
 * properties of undefined (reading 'map')` the moment the real
 * `GET /ideation/ideas/board` response resolved, even though that response
 * is well-formed (every column carries an `ideas` array). `board/page.test.tsx`
 * stayed green throughout because it mocks `useIdeas()` wholesale with
 * already-resolved, synchronous data - it never exercises the loading ->
 * loaded TRANSITION that actually crashed.
 *
 * This suite instead mocks ONLY `apiFetch` at the wire boundary and renders
 * `TriageBoard` through the REAL `useIdeas` hook and the REAL bound
 * `ideationService` (`realIdeationService`, slice S5) - the exact path a
 * browser runs, reproducing the race the jsdom mock-hook suite cannot see.
 *
 * TEST-FIRST: fails with the reported TypeError (thrown from the shared
 * `Kanban` primitive, `components/ui/kanban.tsx`'s `columns[value].map(...)`)
 * until `triage-board.tsx` keeps its `columns` state in lockstep with
 * `source` on the SAME render instead of one `useEffect` commit behind.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TriageBoard } from './triage-board';

vi.mock('@/lib/api-client', () => ({ apiFetch: vi.fn() }));
import { apiFetch } from '@/lib/api-client';
const mockApiFetch = vi.mocked(apiFetch);

// The EXACT live response shape (AC-94-49/51/52/41/54) - IdeaOut fields on
// every board card, BoardColumnOut fields (`statusId`, `key`, `title`,
// `color`, `ideas`) on every column, per the S6 evidence README.
function liveIdea(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'idea-1001',
    productId: 'prod-1',
    productName: 'Sorento CRM',
    status: 'captured',
    statusId: 'st-captured',
    statusLabel: 'New',
    statusColor: 'blue',
    statusIsArchived: false,
    transitions: [
      { id: 'tr-1', label: 'Triage', toStatusId: 'st-triaged', toStatusLabel: 'Triaged' },
    ],
    advanceTransitionId: 'tr-1',
    rank: 1,
    mergedIntoId: null,
    mergedInto: null,
    mergedCount: 0,
    title: null,
    problem: 'Export orders to Excel',
    proposedSolution: null,
    impact: null,
    department: null,
    rawText: 'raw',
    source: 'whatsapp',
    submitterName: 'Aisha Rahman',
    submitterTier: null,
    upvotes: 5,
    downvotes: 0,
    myVote: null,
    priority: 0,
    attachments: [],
    createdAt: '2026-09-28T00:00:00Z',
    ideaNumber: 'IDEA-0001',
    isTest: false,
    ...over,
  };
}

const liveBoardResponse = {
  columns: [
    { statusId: 'st-captured', key: 'captured', title: 'New', color: 'blue', ideas: [liveIdea()] },
    { statusId: 'st-triaged', key: 'triaged', title: 'Triaged', color: 'amber', ideas: [] },
    { statusId: 'st-linked', key: 'linked', title: 'Linked to BR', color: 'violet', ideas: [] },
    { statusId: 'st-building', key: 'building', title: 'Building', color: 'indigo', ideas: [] },
    { statusId: 'st-delivered', key: 'delivered', title: 'Delivered', color: 'emerald', ideas: [] },
  ],
};

beforeEach(() => {
  mockApiFetch.mockReset();
  mockApiFetch.mockImplementation(async (path: unknown) => {
    const p = String(path);
    if (p.startsWith('/ideation/ideas/board')) return liveBoardResponse;
    if (p.startsWith('/ideation/ideas')) return [liveIdea()];
    if (p.startsWith('/products')) {
      return {
        items: [{ id: 'prod-1', name: 'Sorento CRM', kind: 'software' }],
        total: 1,
        page: 0,
        pageSize: 200,
      };
    }
    throw new Error(`unexpected apiFetch path in this test: ${p}`);
  });
});

describe('TriageBoard - real board response through the real service (S6 evidence, AC-94-58)', () => {
  it('renders every column with no crash once the real getBoard response resolves', async () => {
    render(<TriageBoard />);
    // The loading -> loaded transition is exactly what crashed live - assert
    // both sides of it render cleanly.
    expect(screen.getByText(/loading board/i)).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText('New')).toBeInTheDocument());
    expect(screen.getByText('Triaged')).toBeInTheDocument();
    expect(screen.getByText('Linked to BR')).toBeInTheDocument();
    expect(screen.getByText('Building')).toBeInTheDocument();
    expect(screen.getByText('Delivered')).toBeInTheDocument();
    expect(screen.getByText('Export orders to Excel')).toBeInTheDocument();
  });
});
