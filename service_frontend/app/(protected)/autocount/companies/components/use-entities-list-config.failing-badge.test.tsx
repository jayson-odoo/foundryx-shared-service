import { render, renderHook, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEntityConfig } from '@/types/autocount';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const { useAutocountEntitiesListConfig } = await import('./use-entities-list-config');

/**
 * Plan 33 (SS-INTEGRATION-ALERT) AC-33-14 - the company detail's integration
 * list marks a row with an open incident as `Failing`. RED: written before the
 * state exists.
 */
function entity(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'customer',
    syncMode: 'SCHEDULED_REVIEW',
    sourceImpl: 'sql_db',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: '2026-08-30T10:00:00Z',
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'active',
    openIncident: null,
    ...over,
  };
}

function healthCell(row: AutocountEntityConfig) {
  const { result } = renderHook(() =>
    useAutocountEntitiesListConfig({
      entities: [row],
      companyActive: true,
      sourceKind: 'db',
      onSync: vi.fn(),
      onEditLookback: vi.fn(),
      onRefetch: vi.fn(),
      onConfigureMapping: vi.fn(),
      onConfigureTask: vi.fn(),
    }),
  );
  const col = result.current.columns.find((c) => c.id === 'health');
  const cell = col?.cell as (ctx: { row: { original: AutocountEntityConfig } }) => ReactNode;
  return render(<>{cell({ row: { original: row } })}</>);
}

const INCIDENT = {
  openedAt: '2026-08-30T12:00:00Z',
  firstFailureAt: '2026-08-30T11:40:00Z',
  failedRuns: 14,
  lastError: 'AutoCount answered HTTP 502 on page 3.',
  reason: 'consecutive' as const,
};

describe('integration list Failing badge (AC-33-14)', () => {
  it('AC-33-14: a row with an open incident shows a Failing badge', () => {
    healthCell(entity({ openIncident: INCIDENT }));
    expect(screen.getByText('Failing')).toBeInTheDocument();
    expect(screen.queryByText('Healthy')).not.toBeInTheDocument();
  });

  it('AC-33-14: the Failing badge wins over the Healthy / failed-runs states', () => {
    healthCell(entity({ openIncident: INCIDENT, consecutiveFailures: 14, lastError: 'boom' }));
    expect(screen.getByText('Failing')).toBeInTheDocument();
  });

  it('AC-33-14: a stale-only incident (no failed runs counted) is also Failing', () => {
    healthCell(entity({ openIncident: { ...INCIDENT, reason: 'stale', failedRuns: 0 } }));
    expect(screen.getByText('Failing')).toBeInTheDocument();
  });

  it('AC-33-14: no incident, no Failing badge (control)', () => {
    healthCell(entity({ openIncident: null }));
    expect(screen.queryByText('Failing')).not.toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
  });
});
