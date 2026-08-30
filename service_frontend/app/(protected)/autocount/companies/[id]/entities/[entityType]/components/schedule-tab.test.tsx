import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEtlSourceConfig, AutocountEtlTask } from '@/types/autocount';
import { ScheduleTab } from './schedule-tab';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'Asia/Kuala_Lumpur',
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

function config(over: Partial<AutocountEtlSourceConfig> = {}): AutocountEtlSourceConfig {
  return {
    connectionId: 'conn-sql-1',
    query: 'SELECT * FROM dbo.Debtor',
    lineQuery: null,
    keyColumns: ['AccNo'],
    watermarkColumn: null,
    comparedColumns: [],
    fromDate: null,
    incrementalMinutes: 15,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    ...over,
  };
}

function task(over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: config(),
    resultColumns: ['AccNo'],
    lastPreviewAt: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...over,
  };
}

describe('ScheduleTab (plan 22 S3, AC-22-12..17)', () => {
  it('carries the watermark-driven incremental floor on the input (foolproof-UI: no hint copy, N6)', () => {
    const { rerender } = render(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ watermarkColumn: null })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-incremental-minutes')).toHaveAttribute('min', '15');

    rerender(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ watermarkColumn: 'LastModified' })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-incremental-minutes')).toHaveAttribute('min', '1');
  });

  it('shows a floor-violation inline error live, no save required', () => {
    render(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ incrementalMinutes: 5, watermarkColumn: null })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-incremental-error')).toHaveTextContent(/at least 15 minutes/i);
  });

  it('prefers a server field error over the live client mirror', () => {
    render(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ incrementalMinutes: 30 })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{ incrementalMinutes: 'Server-side rejection.' }}
      />,
    );
    expect(screen.getByTestId('etl-incremental-error')).toHaveTextContent('Server-side rejection.');
  });

  it('dailyAt mode renders a time input, the literal UTC (the backend resolves it, not the session timezone), and an invalid-time error', () => {
    render(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ reconcileMode: 'dailyAt', reconcileAt: null })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-reconcile-at')).toBeInTheDocument();
    expect(screen.getByText('UTC')).toBeInTheDocument();
    expect(screen.queryByText('Asia/Kuala_Lumpur')).not.toBeInTheDocument();
    expect(screen.getByTestId('etl-reconcile-at-error')).toHaveTextContent(/HH:MM/);
    expect(screen.queryByTestId('etl-reconcile-hours')).not.toBeInTheDocument();
  });

  it('interval mode renders an hours input and a below-floor error', () => {
    render(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ reconcileMode: 'interval', reconcileHours: 0 })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-reconcile-hours')).toBeInTheDocument();
    expect(screen.getByTestId('etl-reconcile-hours-error')).toHaveTextContent(/at least 1 hour/i);
    expect(screen.queryByTestId('etl-reconcile-at')).not.toBeInTheDocument();
  });

  it('renders read-only text (no inputs) when not editing', () => {
    render(
      <ScheduleTab
        editing={false}
        entityType="customer"
        config={config({ incrementalMinutes: 5, reconcileAt: '03:30' })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
      />,
    );
    expect(screen.queryByTestId('etl-incremental-minutes')).not.toBeInTheDocument();
    expect(screen.queryByTestId('etl-reconcile-at')).not.toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('03:30')).toBeInTheDocument();
  });

  it('shows next-run badges only while the task is active', () => {
    const { rerender } = render(
      <ScheduleTab
        editing={false}
        entityType="customer"
        config={config()}
        onChange={vi.fn()}
        task={task({ etlStatus: 'paused', nextIncrementalAt: '2026-08-30T06:15:00Z' })}
        fieldErrors={{}}
      />,
    );
    expect(screen.queryByTestId('etl-next-incremental-badge')).not.toBeInTheDocument();

    rerender(
      <ScheduleTab
        editing={false}
        entityType="customer"
        config={config()}
        onChange={vi.fn()}
        task={task({
          etlStatus: 'active',
          nextIncrementalAt: '2026-08-30T06:15:00Z',
          nextReconcileAt: '2026-08-31T02:00:00Z',
        })}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-next-incremental-badge')).toHaveTextContent('2026-08-30T06:15:00Z');
    expect(screen.getByTestId('etl-next-reconcile-badge')).toHaveTextContent('2026-08-31T02:00:00Z');
  });

  it('shows the delete guard threshold, and a from-date chip only for document entities', () => {
    const { rerender } = render(
      <ScheduleTab
        editing={false}
        entityType="customer"
        config={config()}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-delete-guard-threshold')).toHaveTextContent('20% of known rows (minimum 50)');
    expect(screen.queryByTestId('etl-schedule-from-date')).not.toBeInTheDocument();

    rerender(
      <ScheduleTab
        editing={false}
        entityType="sales_order"
        config={config({ fromDate: '2026-08-01' })}
        onChange={vi.fn()}
        task={task({ entityType: 'sales_order' })}
        fieldErrors={{}}
      />,
    );
    expect(screen.getByTestId('etl-schedule-from-date')).toHaveTextContent('2026-08-01');
  });
});
