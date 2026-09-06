/**
 * Omnichannel dashboard + reports service (plan 30, roadmap A9). UI -> hook
 * -> service -> lib/api-client. S0 binds the MOCK implementation (returning
 * the UAC fixture's numbers for the canonical range/tz so the whole UI is
 * buildable + testable before any endpoint exists, plan §5.5); S4 swaps this
 * one export to `.real` - no other file changes.
 *
 * The interface IS the backend contract (plan §5.1):
 *
 *   GET  /omnichannel/workspaces/{wsId}/dashboard?from=&to=&tz=&granularity=&userId=&channelId=
 *          -> DashboardResponse
 *   GET  /omnichannel/workspaces/{wsId}/reports/meta -> ReportMeta
 *   GET  /omnichannel/workspaces/{wsId}/reports/{reportKey}?...&page=&pageSize=
 *          -> ReportResponse
 *   POST /omnichannel/workspaces/{wsId}/reports/{reportKey}/export -> { jobId }
 *   GET  /omnichannel/workspaces/{wsId}/reports/{reportKey}/export/{jobId}/file
 *          -> text/csv (via lib/api-client apiFetchBlob)
 *
 * `exportReport` mirrors the shape of `ContactService.exportContacts` (the
 * A2 precedent, plan 26): create the job, poll briefly, resolve the finished
 * CSV text, or throw the SHARED `ExportPendingError` (lib/service-errors.ts)
 * when the wait window elapses so the caller can point the user at Jobs
 * instead of a bare failure - never a silent one.
 */
import type { DashboardResponse, ReportExportRequest, ReportFilters, ReportKey, ReportMeta, ReportResponse } from '@/types/omnichannel';
import { mockOmnichannelReportService } from './omnichannel-report-service.mock';

/** `reports/{key}` read query - the base filters plus the two paginated
 *  reports' page params (ignored server-side by non-paginated reports). */
export type ReportQuery = ReportFilters & { page?: number; pageSize?: number };

export interface OmnichannelReportService {
  /** The seven report descriptors + granularities + the team-dimension
   *  availability flag (D-A9-13 - absent/false until plan 28 lands). */
  meta(workspaceId: string): Promise<ReportMeta>;
  dashboard(workspaceId: string, filters: ReportFilters): Promise<DashboardResponse>;
  /**
   * Returns the generic envelope (`rows`/`totals` typed `object`/`object[]`
   * by the type's own defaults) - each report hook/renderer casts to its own
   * concrete `ReportResponse<TRow, TTotals>` (the per-report shapes in
   * `types/omnichannel.ts`), since a single object-literal implementation
   * can't be generic over what the CALLER asks for.
   */
  report(workspaceId: string, reportKey: ReportKey, query: ReportQuery): Promise<ReportResponse>;
  /** Creates the `background_jobs` export row (D-A9-4), polls briefly, then
   *  resolves the CSV text of the finished job. Throws `ExportPendingError`
   *  (lib/service-errors.ts) when the job hasn't finished inside the wait
   *  window. */
  exportReport(workspaceId: string, reportKey: ReportKey, filters: ReportExportRequest): Promise<string>;
}

// S0 MOCK - swap to real in S4 (plan 30).
export const omnichannelReportService: OmnichannelReportService = mockOmnichannelReportService;
