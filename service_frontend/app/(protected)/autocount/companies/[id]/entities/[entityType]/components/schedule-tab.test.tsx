import { fireEvent, render, screen } from '@testing-library/react';
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
    docDateColumn: null,
      filterFormula: null,
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
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...over,
  };
}

describe('ScheduleTab (plan 22 S3, AC-22-12..17; floor 5 sprint-5/13 D11/AC-13-20)', () => {
  it('carries the watermark-driven incremental floor on the input (foolproof-UI: no hint copy, N6)', () => {
    const { rerender } = render(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ watermarkColumn: null })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-incremental-minutes')).toHaveAttribute('min', '5');

    rerender(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ watermarkColumn: 'LastModified' })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-incremental-minutes')).toHaveAttribute('min', '1');
  });

  it('shows a floor-violation inline error live, no save required', () => {
    render(
      <ScheduleTab
        editing
        entityType="customer"
        config={config({ incrementalMinutes: 4, watermarkColumn: null })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-incremental-error')).toHaveTextContent(/at least 5 minutes/i);
  });

  it('AC-13-20/41: 5 minutes clears the error, no-watermark entity', () => {
    render(
      <ScheduleTab
        editing
        entityType="stock_balance"
        config={config({ incrementalMinutes: 5, watermarkColumn: null })}
        onChange={vi.fn()}
        task={task({ entityType: 'stock_balance' })}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('etl-incremental-error')).not.toBeInTheDocument();
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
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
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-schedule-from-date')).toHaveTextContent('2026-08-01');
  });
});

describe('ScheduleTab delivery toggle (sprint-5/10, AC-10-16)', () => {
  it('Pull hides the incremental/reconcile cadence controls entirely, keeping their values in config', () => {
    render(
      <ScheduleTab
        editing
        entityType="product"
        config={config({ incrementalMinutes: 42 })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
        deliveryMode="pull"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('etl-incremental-minutes')).not.toBeInTheDocument();
    expect(screen.queryByTestId('etl-reconcile-at')).not.toBeInTheDocument();
    expect(screen.queryByTestId('etl-delete-guard-threshold')).not.toBeInTheDocument();
  });

  it('Push restores the cadence controls unchanged', () => {
    render(
      <ScheduleTab
        editing
        entityType="product"
        config={config({ incrementalMinutes: 42 })}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-incremental-minutes')).toHaveValue(42);
  });

  it('the toggle calls onDeliveryModeChange', () => {
    const onDeliveryModeChange = vi.fn();
    render(
      <ScheduleTab
        editing
        entityType="product"
        config={config()}
        onChange={vi.fn()}
        task={task()}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={onDeliveryModeChange}
      />,
    );
    fireEvent.click(screen.getByTestId('etl-delivery-pull'));
    expect(onDeliveryModeChange).toHaveBeenCalledWith('pull');
  });

  it('a pull-only entity (push gate shut) shows a read-only badge, no toggle at all', () => {
    render(
      <ScheduleTab
        editing
        entityType="stock_balance"
        config={config()}
        onChange={vi.fn()}
        task={task({
          entityType: 'stock_balance',
          pushGate: { version: 2.4, requiredVersion: 2.5 },
        })}
        fieldErrors={{}}
        deliveryMode="pull"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('etl-delivery-push')).not.toBeInTheDocument();
    expect(screen.queryByTestId('etl-delivery-pull')).not.toBeInTheDocument();
    expect(screen.getByText('Pull on request')).toBeInTheDocument();
  });
});

describe('ScheduleTab push gate (sprint-5/13, D18, AC-13-40)', () => {
  it('a non-null pushGate never renders the toggle, whatever the entity type', () => {
    render(
      <ScheduleTab
        editing
        entityType="stock_balance"
        config={config()}
        onChange={vi.fn()}
        task={task({
          entityType: 'stock_balance',
          pushGate: { version: 2.4, requiredVersion: 2.5 },
        })}
        fieldErrors={{}}
        deliveryMode="pull"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole('radio', { name: 'Push' })).not.toBeInTheDocument();
    expect(screen.getByTestId('etl-push-gate-warning')).toHaveTextContent(
      'Consumer contract 2.4 - stock push needs 2.5.',
    );
  });

  it('a null pushGate renders the toggle instead of a badge - AC-13-40 "opens with no code change"', () => {
    render(
      <ScheduleTab
        editing
        entityType="stock_balance"
        config={config()}
        onChange={vi.fn()}
        task={task({ entityType: 'stock_balance', pushGate: null })}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-delivery-push')).toBeInTheDocument();
    expect(screen.getByTestId('etl-delivery-pull')).toBeInTheDocument();
    expect(screen.queryByTestId('etl-push-gate-warning')).not.toBeInTheDocument();
  });

  it('the shut badge names the CURRENT delivery mode, not a hardcoded "Pull on request"', () => {
    render(
      <ScheduleTab
        editing
        entityType="stock_balance"
        config={config()}
        onChange={vi.fn()}
        task={task({
          entityType: 'stock_balance',
          pushGate: { reason: 'no_snapshot' },
        })}
        fieldErrors={{}}
        deliveryMode="push"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Push')).toBeInTheDocument();
    expect(screen.getByTestId('etl-push-gate-warning')).toHaveTextContent(
      'Push needs a stock snapshot from the last 24 hours.',
    );
  });

  it('no entity-list hardcoding: a non-stock entity with a (hypothetical) shut gate ALSO shows the badge', () => {
    render(
      <ScheduleTab
        editing
        entityType="product"
        config={config()}
        onChange={vi.fn()}
        task={task({ entityType: 'product', pushGate: { version: 2.3, requiredVersion: 2.5 } })}
        fieldErrors={{}}
        deliveryMode="pull"
        onDeliveryModeChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('etl-delivery-push')).not.toBeInTheDocument();
    expect(screen.getByTestId('etl-push-gate-warning')).toBeInTheDocument();
  });
});
