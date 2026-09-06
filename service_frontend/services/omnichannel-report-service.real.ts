/**
 * Real dashboard + reports service (plan 30 S4) - talks to the S1-S3 backend
 * routes documented on `omnichannel-report-service.ts`. Not wired yet (S0 is
 * frontend-mock only, this file exists so the barrel type-checks and the S4
 * swap is a one-line change); every method mirrors `ContactService`'s real
 * implementation shape (plan 26) - a query-string builder + `apiFetch`, and
 * `exportReport` polling `/jobs/{id}` before resolving the CSV text.
 */
import { apiFetch, apiFetchBlob, ApiError } from '@/lib/api-client';
import { ExportPendingError } from '@/lib/service-errors';
import type { Job } from '@/types/jobs';
import type { DashboardResponse, ReportExportRequest, ReportFilters, ReportKey, ReportMeta, ReportResponse } from '@/types/omnichannel';
import type { OmnichannelReportService, ReportQuery } from './omnichannel-report-service';

const EXPORT_POLL_INTERVAL_MS = 400;
const EXPORT_WAIT_ATTEMPTS = 5; // ~2s before falling back to the Jobs surface

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function filterParams(filters: ReportFilters): URLSearchParams {
  const params = new URLSearchParams({ from: filters.from, to: filters.to, tz: filters.tz });
  if (filters.granularity) params.set('granularity', filters.granularity);
  if (filters.userId) params.set('userId', filters.userId);
  if (filters.channelId) params.set('channelId', filters.channelId);
  if (filters.groupBy) params.set('groupBy', filters.groupBy);
  return params;
}

async function waitForExportJob(jobId: string): Promise<Job> {
  for (let attempt = 0; attempt < EXPORT_WAIT_ATTEMPTS; attempt++) {
    const job = await apiFetch<Job>(`/jobs/${jobId}`);
    if (job.status === 'done' || job.status === 'failed' || job.status === 'aborted') return job;
    await wait(EXPORT_POLL_INTERVAL_MS);
  }
  throw new ExportPendingError('The export is still running - it will finish in Jobs.', jobId);
}

export const realOmnichannelReportService: OmnichannelReportService = {
  meta(workspaceId: string) {
    return apiFetch<ReportMeta>(`/omnichannel/workspaces/${workspaceId}/reports/meta`);
  },

  dashboard(workspaceId: string, filters: ReportFilters) {
    return apiFetch<DashboardResponse>(
      `/omnichannel/workspaces/${workspaceId}/dashboard?${filterParams(filters).toString()}`,
    );
  },

  report(workspaceId: string, reportKey: ReportKey, query: ReportQuery) {
    const params = filterParams(query);
    if (query.page != null) params.set('page', String(query.page));
    if (query.pageSize != null) params.set('pageSize', String(query.pageSize));
    return apiFetch<ReportResponse>(
      `/omnichannel/workspaces/${workspaceId}/reports/${reportKey}?${params.toString()}`,
    );
  },

  async exportReport(workspaceId: string, reportKey: ReportKey, filters: ReportExportRequest) {
    const { jobId } = await apiFetch<{ jobId: string }>(
      `/omnichannel/workspaces/${workspaceId}/reports/${reportKey}/export`,
      { method: 'POST', body: JSON.stringify(filters) },
    );
    const job = await waitForExportJob(jobId);
    if (job.status === 'failed' || job.status === 'aborted') {
      throw new ApiError(job.error ?? 'The export could not be completed.', 500);
    }
    const blob = await apiFetchBlob(
      `/omnichannel/workspaces/${workspaceId}/reports/${reportKey}/export/${jobId}/file`,
    );
    return blob.text();
  },
};
