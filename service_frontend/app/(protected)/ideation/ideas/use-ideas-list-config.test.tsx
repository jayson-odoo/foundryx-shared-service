import { describe, expect, it, vi } from 'vitest';
import { render, renderHook, screen } from '@testing-library/react';
import type { Idea } from '@/types/ideation';
import { useIdeasListConfig } from './use-ideas-list-config';

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

const handlers = () => ({
  onCreate: vi.fn(),
  onVote: vi.fn(),
  onAdvance: vi.fn(),
  onArchive: vi.fn(),
  onRestore: vi.fn(),
  onDelete: vi.fn(),
  onReorder: vi.fn(),
  onPromote: vi.fn(),
});

function config(ideas: Idea[]) {
  const { result } = renderHook(() => useIdeasListConfig(ideas, handlers()));
  return result.current;
}

// ── issue #1179 - Promote to BR foolproof-disable on a test idea ──────────────

describe('useIdeasListConfig - promote-br action', () => {
  it('is NOT disabled for a same-product selection of real ideas', () => {
    const cfg = config([anIdea()]);
    const promote = cfg.actions.find((a) => a.id === 'promote-br')!;
    expect(promote.isDisabled?.([anIdea({ id: 'a' }), anIdea({ id: 'b' })])).toBe(false);
  });

  it('is disabled when any selected row is a test idea', () => {
    const cfg = config([anIdea()]);
    const promote = cfg.actions.find((a) => a.id === 'promote-br')!;
    expect(
      promote.isDisabled?.([anIdea({ id: 'a' }), anIdea({ id: 'b', isTest: true })]),
    ).toBe(true);
    // A lone test idea is disabled too, not just a mixed selection.
    expect(promote.isDisabled?.([anIdea({ id: 'a', isTest: true })])).toBe(true);
  });
});

// ── issue #1179 - TEST badge on the idea column ────────────────────────────────

describe('useIdeasListConfig - Idea column TEST badge', () => {
  it('renders the TEST badge for an isTest row', () => {
    const cfg = config([anIdea({ isTest: true })]);
    const column = cfg.columns.find((c) => c.id === 'problem')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    render(<>{cell({ row: { original: anIdea({ isTest: true }) } })}</>);
    expect(screen.getByText('TEST')).toBeInTheDocument();
    expect(screen.getByText('Export orders to Excel')).toBeInTheDocument();
  });

  it('does not render the TEST badge for a real row', () => {
    const cfg = config([anIdea()]);
    const column = cfg.columns.find((c) => c.id === 'problem')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    render(<>{cell({ row: { original: anIdea({ isTest: false }) } })}</>);
    expect(screen.queryByText('TEST')).not.toBeInTheDocument();
  });
});
