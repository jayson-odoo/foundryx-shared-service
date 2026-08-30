import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { UseEtlTaskLifecycleResult, UseEtlTaskPreviewResult } from '@/hooks/use-autocount-etl';
import type { AutocountCompany, AutocountEtlTask } from '@/types/autocount';
import { ActivateTab } from './activate-tab';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

function company(over: Partial<AutocountCompany> = {}): AutocountCompany {
  return {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED',
    companyName: 'AED',
    name: 'AED',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-9',
    sorentoCompanyCode: 'SRT',
    createdAt: null,
    ...over,
  };
}

function task(over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-sql-1',
      query: 'SELECT * FROM dbo.Debtor',
      lineQuery: null,
      keyColumns: ['AccNo'],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo'],
    lastPreviewAt: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    ...over,
  };
}

function preview(state: UseEtlTaskPreviewResult['state'] = { status: 'idle' }): UseEtlTaskPreviewResult {
  return { state, run: vi.fn().mockResolvedValue(undefined), reset: vi.fn() };
}

function lifecycle(over: Partial<UseEtlTaskLifecycleResult> = {}): UseEtlTaskLifecycleResult {
  return {
    busy: null,
    error: null,
    activate: vi.fn().mockResolvedValue(true),
    pause: vi.fn().mockResolvedValue(true),
    resume: vi.fn().mockResolvedValue(true),
    runNow: vi.fn().mockResolvedValue('run-1'),
    clearError: vi.fn(),
    ...over,
  };
}

describe('ActivateTab (plan 22 S2, AC-22-18/19, Appendix A6)', () => {
  it('withholds Activate until a preview passed, then enables it', () => {
    const { rerender } = render(
      <ActivateTab company={company()} task={task()} configDirty={false} preview={preview()} lifecycle={lifecycle()} onRan={vi.fn()} />,
    );
    expect(screen.getByTestId('etl-run-preview')).toBeEnabled();
    expect(screen.getByTestId('etl-activate')).toBeDisabled();
    expect(screen.getByTestId('activate-blocked')).toBeInTheDocument();

    rerender(
      <ActivateTab
        company={company()}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
    expect(screen.getByTestId('etl-preview-passed')).toBeInTheDocument();
  });

  it('withholds both buttons with a stated prerequisite when the company has no Sorento code', () => {
    render(
      <ActivateTab
        company={company({ sorentoCompanyCode: null })}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('activate-prerequisite-companyCode')).toHaveTextContent(/Open company/);
    expect(screen.getByTestId('etl-run-preview')).toBeDisabled();
    expect(screen.getByTestId('etl-activate')).toBeDisabled();
  });

  it('withholds on unsaved edits (a preview of an unsaved query proves nothing)', () => {
    render(
      <ActivateTab company={company()} task={task()} configDirty preview={preview()} lifecycle={lifecycle()} onRan={vi.fn()} />,
    );
    expect(screen.getByTestId('activate-prerequisite-unsaved')).toBeInTheDocument();
    expect(screen.getByTestId('etl-run-preview')).toBeDisabled();
  });

  it('renders a Sorento anchor 422 as a task-level error with its title, not a dry-run failure', () => {
    render(
      <ActivateTab
        company={company()}
        task={task()}
        configDirty={false}
        preview={preview({
          status: 'taskError',
          error: { code: 'COMPANY_ANCHOR_AMBIGUOUS', message: 'Two companies match.' },
        })}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    const alert = screen.getByTestId('etl-task-error');
    expect(alert).toHaveTextContent('Sorento company code is ambiguous');
    expect(alert).toHaveTextContent('Two companies match.');
    expect(screen.queryByTestId('preview-error')).not.toBeInTheDocument();
  });

  it('shows Pause + Run now while active, Resume while paused, and the last run error on the task', async () => {
    const lc = lifecycle();
    const onRan = vi.fn();
    const { rerender } = render(
      <ActivateTab
        company={company()}
        task={task({ etlStatus: 'active', activatedAt: '2026-08-30T06:30:00Z', lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lc}
        onRan={onRan}
      />,
    );
    expect(screen.queryByTestId('etl-activate')).not.toBeInTheDocument();
    expect(screen.getByTestId('etl-pause')).toBeEnabled();
    fireEvent.click(screen.getByTestId('etl-run-now'));
    await vi.waitFor(() => expect(onRan).toHaveBeenCalled());

    rerender(
      <ActivateTab
        company={company()}
        task={task({
          etlStatus: 'paused',
          lastRunAt: '2026-08-30T06:40:00Z',
          lastRunError: "No Sorento company matches code 'ZZ'.",
          lastRunErrorCode: 'UNKNOWN_COMPANY',
        })}
        configDirty={false}
        preview={preview()}
        lifecycle={lc}
        onRan={onRan}
      />,
    );
    expect(screen.getByTestId('etl-resume')).toBeEnabled();
    expect(screen.getByTestId('task-last-run-error')).toHaveTextContent('Unknown Sorento company');
  });
});
