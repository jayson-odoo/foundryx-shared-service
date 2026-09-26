import { describe, expect, it, vi } from 'vitest';
import { render, renderHook, screen } from '@testing-library/react';
import type { ListQuery } from '@/types/resource';
import type { BusinessRequirement } from '@/types/business-requirement';
import { useBrListConfig } from './use-br-list-config';

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
  ideaCount: 2,
  createdAt: '2026-07-20T10:00:00Z',
  updatedAt: '2026-07-20T10:00:00Z',
  ...over,
});

const query: ListQuery = { page: 0, pageSize: 25, search: '', sort: undefined, filter: null };

function config(rows: BusinessRequirement[]) {
  const { result } = renderHook(() =>
    useBrListConfig(rows, { onCreate: vi.fn(), onDelete: vi.fn() }),
  );
  return result.current;
}

describe('useBrListConfig', () => {
  it('gates create on the manage permission and uses the BR view key', () => {
    const cfg = config([br()]);
    expect(cfg.createPermission).toBe('ideation.business_requirements.manage');
    expect(cfg.viewKey).toBe('ideation.business_requirements');
    expect(cfg.enableStatusViews).toBe(true);
  });

  it('active view hides archived BRs; archived view shows only them', async () => {
    const rows = [br({ id: 'a', status: 'draft' }), br({ id: 'b', status: 'archived' })];
    const cfg = config(rows);
    const active = await cfg.fetcher({ ...query });
    expect(active.data.map((r) => r.id)).toEqual(['a']);
    const archived = await cfg.fetcher({ ...query, statusView: 'trashed' });
    expect(archived.data.map((r) => r.id)).toEqual(['b']);
  });

  it('search matches title and product', async () => {
    const rows = [
      br({ id: 'a', title: 'Export orders', productName: 'CRM' }),
      br({ id: 'b', title: 'Invoices', productName: 'Billing' }),
    ];
    const cfg = config(rows);
    const res = await cfg.fetcher({ ...query, search: 'export' });
    expect(res.data.map((r) => r.id)).toEqual(['a']);
  });

  it('exposes a delete action on row/form/bulk surfaces', () => {
    const cfg = config([br()]);
    const del = cfg.actions.find((a) => a.id === 'delete');
    expect(del).toBeTruthy();
    expect(del?.surfaces).toMatchObject({ row: true, form: true, bulk: true });
  });
});

// ── issue #90 W3 - TEST badge on a test Business Requirement ──────────────────

describe('useBrListConfig - AC-90-310 title column TEST badge', () => {
  it('renders the TEST badge for an isTest row', () => {
    const cfg = config([br({ isTest: true } as Partial<BusinessRequirement>)]);
    const column = cfg.columns.find((c) => c.id === 'title')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    render(
      <>{cell({ row: { original: br({ isTest: true } as Partial<BusinessRequirement>) } })}</>,
    );
    expect(screen.getByText('TEST')).toBeInTheDocument();
    expect(screen.getByText('Order export')).toBeInTheDocument();
  });

  it('does not render the TEST badge for a real row', () => {
    const cfg = config([br()]);
    const column = cfg.columns.find((c) => c.id === 'title')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    render(<>{cell({ row: { original: br() } })}</>);
    expect(screen.queryByText('TEST')).not.toBeInTheDocument();
  });
});
