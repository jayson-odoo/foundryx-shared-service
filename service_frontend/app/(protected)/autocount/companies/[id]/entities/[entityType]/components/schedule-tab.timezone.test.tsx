import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEtlSourceConfig, AutocountEtlTask } from '@/types/autocount';
import { reconcileTimezoneLabel } from '@/lib/autocount-etl';
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
    query: 'SELECT 1',
    lineQuery: null,
    keyColumns: ['AccNo'],
    watermarkColumn: 'LastModified',
    comparedColumns: [],
    fromDate: null,
    docDateColumn: null,
    filterFormula: null,
    incrementalMinutes: 1,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    ...over,
  };
}

const task = {
  companyId: 'c1',
  entityType: 'sales_order',
  etlStatus: 'draft',
  activatedAt: null,
  sourceConfig: config(),
  resultColumns: [],
  lastPreviewAt: null,
  lastPreviewFailedCount: null,
  lastRunAt: null,
  lastRunError: null,
  lastRunErrorCode: null,
  nextIncrementalAt: null,
  nextReconcileAt: null,
} as unknown as AutocountEtlTask;

function renderTab(over: Partial<AutocountEtlSourceConfig>) {
  render(
    <ScheduleTab
      editing={false}
      entityType="sales_order"
      config={config(over)}
      onChange={vi.fn()}
      task={task}
      fieldErrors={{}}
      deliveryMode="push"
      onDeliveryModeChange={vi.fn()}
    />,
  );
}

describe('ScheduleTab reconcile time zone (SS-SO-FAST-QUEUE)', () => {
  it('shows MYT for a task stored in Asia/Kuala_Lumpur', () => {
    renderTab({ reconcileTimezone: 'Asia/Kuala_Lumpur' });
    expect(screen.getByTestId('etl-reconcile-timezone')).toHaveTextContent('MYT');
  });

  it('shows UTC for a task saved before the zone existed', () => {
    renderTab({});
    expect(screen.getByTestId('etl-reconcile-timezone')).toHaveTextContent('UTC');
  });

  it('labels zones', () => {
    expect(reconcileTimezoneLabel(undefined)).toBe('UTC');
    expect(reconcileTimezoneLabel('UTC')).toBe('UTC');
    expect(reconcileTimezoneLabel('Asia/Kuala_Lumpur')).toBe('MYT');
  });
});
