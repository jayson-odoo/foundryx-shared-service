'use client';

/**
 * Report export controller (plan 30, AC-RPT-47) - the exact A2 contacts-
 * export shape (create the job, poll briefly, resolve CSV text OR throw
 * `ExportPendingError`), reused not re-implemented: this hook is generic
 * over ANY report key, and `omnichannelReportService.exportReport` (see its
 * `.real.ts`) is the one place that owns the poll loop.
 */
import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from '@/lib/toast';
import { ExportPendingError } from '@/lib/service-errors';
import { omnichannelReportService } from '@/services/omnichannel-report-service';
import type { ReportFilters, ReportKey } from '@/types/omnichannel';
import { reportExportPendingToast } from '../../components/export-pending-toast';

export interface UseReportExportResult {
  exporting: boolean;
  runExport: () => Promise<void>;
}

function downloadCsv(reportKey: ReportKey, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${reportKey}-export.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function useReportExport(
  workspaceId: string | null,
  reportKey: ReportKey,
  filters: ReportFilters,
): UseReportExportResult {
  const router = useRouter();
  const [exporting, setExporting] = useState(false);

  const runExport = useCallback(async () => {
    if (!workspaceId) return;
    setExporting(true);
    try {
      const csv = await omnichannelReportService.exportReport(workspaceId, reportKey, filters);
      downloadCsv(reportKey, csv);
    } catch (error) {
      if (error instanceof ExportPendingError) {
        reportExportPendingToast(router.push);
        return;
      }
      toast.error('The export could not be completed.');
    } finally {
      setExporting(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, reportKey, JSON.stringify(filters), router]);

  return { exporting, runExport };
}
