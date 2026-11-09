import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEtlSourceConfig, AutocountEtlTask } from '@/types/autocount';
import { quietHoursErrors } from '@/lib/autocount-etl';
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
    keyColumns: ['DocKey'],
    watermarkColumn: 'LastModified',
    comparedColumns: [],
    fromDate: null,
    docDateColumn: null,
    filterFormula: null,
    incrementalMinutes: 1,
    incrementalSeconds: 15,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    reconcileTimezone: 'Asia/Kuala_Lumpur',
    quietHoursEnabled: false,
    quietHoursStart: '22:00',
    quietHoursEnd: '07:00',
    quietHoursTimezone: 'Asia/Kuala_Lumpur',
    ...over,
  };
}

const task = {
  companyId: 'c1',
  entityType: 'sales_order',
  etlStatus: 'active',
  sourceConfig: config(),
  resultColumns: [],
  nextIncrementalAt: '2026-11-09T23:00:00Z',
  nextReconcileAt: '2026-11-09T18:00:00Z',
} as unknown as AutocountEtlTask;

function renderTab(
  over: Partial<AutocountEtlSourceConfig>,
  { editing = false, onChange = vi.fn(), fieldErrors = {} } = {},
) {
  render(
    <ScheduleTab
      editing={editing}
      entityType="sales_order"
      config={config(over)}
      onChange={onChange}
      task={task}
      fieldErrors={fieldErrors}
      deliveryMode="push"
      onDeliveryModeChange={vi.fn()}
    />,
  );
  return onChange;
}

describe('ScheduleTab off hours (SS-QUIET-HOURS)', () => {
  it('shows the suggested window switched off, read in MYT', () => {
    renderTab({});
    expect(screen.getByTestId('etl-off-hours')).toHaveTextContent('22:00');
    expect(screen.getByTestId('etl-off-hours')).toHaveTextContent('07:00');
    expect(screen.getByTestId('etl-quiet-enabled')).not.toBeChecked();
    expect(screen.getByTestId('etl-quiet-timezone')).toHaveTextContent('MYT');
  });

  it('switching on sends the flag and the zone', () => {
    const onChange = renderTab({}, { editing: true });
    fireEvent.click(screen.getByTestId('etl-quiet-enabled'));
    expect(onChange).toHaveBeenCalledWith({
      quietHoursEnabled: true,
      quietHoursTimezone: 'Asia/Kuala_Lumpur',
    });
  });

  it('edits the end time', () => {
    const onChange = renderTab({ quietHoursEnabled: true }, { editing: true });
    fireEvent.change(screen.getByTestId('etl-quiet-end'), { target: { value: '06:30' } });
    expect(onChange).toHaveBeenCalledWith({ quietHoursEnd: '06:30' });
  });

  it('time inputs are locked while the window is off', () => {
    renderTab({}, { editing: true });
    expect(screen.getByTestId('etl-quiet-start')).toBeDisabled();
  });

  it('flags the same start and end live, and shows a server error', () => {
    renderTab({ quietHoursEnabled: true, quietHoursEnd: '22:00' }, { editing: true });
    expect(screen.getByTestId('etl-quiet-end-error')).toBeInTheDocument();
  });

  it('server error wins', () => {
    renderTab(
      { quietHoursEnabled: true },
      { editing: true, fieldErrors: { quietHoursStart: 'Server says no.' } },
    );
    expect(screen.getByTestId('etl-quiet-start-error')).toHaveTextContent('Server says no.');
  });

  it('mirrors the server rules', () => {
    expect(quietHoursErrors({ quietHoursEnabled: false, quietHoursStart: '' })).toEqual({});
    expect(
      quietHoursErrors({ quietHoursEnabled: true, quietHoursStart: '22:00', quietHoursEnd: '07:00' }),
    ).toEqual({});
    expect(
      Object.keys(quietHoursErrors({ quietHoursEnabled: true, quietHoursStart: '9pm', quietHoursEnd: '' })),
    ).toEqual(['quietHoursStart', 'quietHoursEnd']);
  });
});
