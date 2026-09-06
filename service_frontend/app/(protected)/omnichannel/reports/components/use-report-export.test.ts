import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ExportPendingError } from '@/lib/service-errors';

const exportReport = vi.fn();
vi.mock('@/services/omnichannel-report-service', () => ({
  omnichannelReportService: { exportReport: (...args: unknown[]) => exportReport(...args) },
}));

const toastInfo = vi.fn();
const toastError = vi.fn();
vi.mock('@/lib/toast', () => ({
  toast: { info: (...a: unknown[]) => toastInfo(...a), error: (...a: unknown[]) => toastError(...a) },
}));

import { useReportExport } from './use-report-export';

const FILTERS = { from: '2026-03-01', to: '2026-03-07', tz: 'Asia/Kuala_Lumpur' };

describe('useReportExport', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    URL.createObjectURL = vi.fn(() => 'blob:mock');
    URL.revokeObjectURL = vi.fn();
  });

  it('downloads the CSV on success', async () => {
    exportReport.mockResolvedValue('"a","b"\n1,2');
    const { result } = renderHook(() => useReportExport('ws-1', 'assignments', FILTERS));

    await act(async () => {
      await result.current.runExport();
    });

    expect(exportReport).toHaveBeenCalledWith('ws-1', 'assignments', FILTERS);
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(result.current.exporting).toBe(false);
  });

  it('falls back to a Jobs toast when the export is still pending', async () => {
    exportReport.mockRejectedValue(new ExportPendingError('The export is still running - it will finish in Jobs.', 'job-1'));
    const { result } = renderHook(() => useReportExport('ws-1', 'assignments', FILTERS));

    await act(async () => {
      await result.current.runExport();
    });

    expect(toastInfo).toHaveBeenCalledWith(
      expect.stringContaining('still running'),
      expect.objectContaining({ action: expect.objectContaining({ label: 'View Jobs' }) }),
    );
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('toasts an error for any other failure', async () => {
    exportReport.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useReportExport('ws-1', 'assignments', FILTERS));

    await act(async () => {
      await result.current.runExport();
    });

    expect(toastError).toHaveBeenCalledWith('The export could not be completed.');
  });

  it('sets exporting=true while the call is in flight', async () => {
    let resolveFn!: (v: string) => void;
    exportReport.mockReturnValue(new Promise<string>((r) => (resolveFn = r)));
    const { result } = renderHook(() => useReportExport('ws-1', 'assignments', FILTERS));

    let pending!: Promise<void>;
    act(() => {
      pending = result.current.runExport();
    });
    await waitFor(() => expect(result.current.exporting).toBe(true));

    await act(async () => {
      resolveFn('a\n1');
      await pending;
    });
    expect(result.current.exporting).toBe(false);
  });

  it('does nothing without a resolved workspace', async () => {
    const { result } = renderHook(() => useReportExport(null, 'assignments', FILTERS));
    await act(async () => {
      await result.current.runExport();
    });
    expect(exportReport).not.toHaveBeenCalled();
  });
});
