/**
 * Real AutoCount service - talks to FastAPI via the shared api-client. Router
 * prefixes come from the module manifest: companies at `/autocount/companies`,
 * sync at `/autocount`.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  AutocountApiConnection,
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyCreateInput,
  AutocountCompanyDetail,
  AutocountEntityConfig,
  AutocountEtlSourceConfig,
  AutocountEtlPreviewResult,
  AutocountEtlRepushResult,
  AutocountEtlRunStart,
  AutocountEtlTask,
  AutocountEtlTaskUpdate,
  AutocountFormulaTestResult,
  AutocountJobListQuery,
  AutocountMappingPreset,
  AutocountMappingUpdate,
  AutocountMappingView,
  AutocountMappingWriteRow,
  AutocountPreviewResult,
  AutocountSimulateResult,
  AutocountSqlConnection,
  AutocountSqlPreview,
  AutocountSqlSchema,
  AutocountStagedList,
  AutocountSyncJob,
  AutocountSyncJobBatch,
  AutocountSyncRun,
  HttpPreview,
  HttpPreviewInput,
} from '@/types/autocount';
import type { ListResult } from '@/types/resource';
import type { AutocountStagedQuery } from '@/types/autocount';
import type { AutocountListQuery, AutocountService } from './autocount-service';

function pageParams(query: AutocountListQuery = {}): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page ?? 0));
  // The backend caps page_size at 200 - asking for more is a 422, not a bigger
  // page, so never send an uncapped "give me everything" size.
  p.set('page_size', String(Math.min(query.pageSize ?? 25, 200)));
  return p;
}

function stagedParams(query: AutocountStagedQuery = {}): URLSearchParams {
  const p = pageParams(query);
  if (query.search) p.set('search', query.search);
  if (query.changed !== undefined) p.set('changed', String(query.changed));
  if (query.status) p.set('status', query.status);
  return p;
}

// sprint-5/08 review round 1 (S5 live-verify DEFECT found against the real
// backend, NOT patched around) - `default_http_source_config()`
// (`modules/autocount/services/etl_service.py`) DELIBERATELY never merges
// the SQL-shape keys (AC-08-30: "never a stray SQL key round-trips onto an
// HTTP task's wire config"), so a REAL saved `autocount_http` task's
// `sourceConfig` omits `query`/`lineQuery`/`keyColumns`/`watermarkColumn`/
// `comparedColumns`/`fromDate`/`docDateColumn`/`filterFormula` entirely.
// Every FE consumer (`task-editor-view.tsx`'s baseline dirty-check,
// `SourceTab`'s `canTest`, ...) was written against the `AutocountEtlTask`
// TYPE contract, which declares those fields non-optional (the mock always
// filled them) - `seeded.query.trim()` crashed with "Cannot read properties
// of undefined" live-verifying AC-08-21 (Add entity -> Test -> Save on a
// fresh HTTP task). Normalized HERE, at the wire boundary, rather than
// `?.`-guarding every read site across the component tree - applied to
// EVERY endpoint that returns or embeds an `AutocountEtlTask` (`getEtlTask`,
// `updateEtlTask`, `activateEtlTask`, `pauseEtlTask`, `resumeEtlTask`,
// `runEtlTaskNow`, `previewEtlTask` - round 5 fix extended it past the first
// two, see `autocount-service.real.test.ts`).
const SQL_SHAPE_DEFAULTS: Pick<
  AutocountEtlSourceConfig,
  | 'query'
  | 'lineQuery'
  | 'keyColumns'
  | 'watermarkColumn'
  | 'comparedColumns'
  | 'fromDate'
  | 'docDateColumn'
  | 'filterFormula'
> = {
  query: '',
  lineQuery: null,
  keyColumns: [],
  watermarkColumn: null,
  comparedColumns: [],
  fromDate: null,
  docDateColumn: null,
  filterFormula: null,
};

function normalizeEtlTask(task: AutocountEtlTask): AutocountEtlTask {
  return { ...task, sourceConfig: { ...SQL_SHAPE_DEFAULTS, ...task.sourceConfig } };
}

export const realAutocountService: AutocountService = {
  // Companies: `sourceKind` (list + detail) and `documentPrerequisites`
  // (detail; the list sends `[]`) ride the backend JSON through untouched
  // (plan sprint-5/01 AC-01-07/11 - `CompanyItem` in `modules/autocount/schemas.py`).
  listCompanies(query = {}) {
    return apiFetch<ListResult<AutocountCompany>>(
      `/autocount/companies?${pageParams(query).toString()}`,
    );
  },

  getCompany(id) {
    return apiFetch<AutocountCompanyDetail>(`/autocount/companies/${id}`);
  },

  createCompany(input: AutocountCompanyCreateInput) {
    return apiFetch<AutocountCompany>('/autocount/companies', {
      method: 'POST',
      body: JSON.stringify({
        connectionId: input.connectionId,
        name: input.name ?? '',
        // Only sent when set - an open (no-auth) connection requires it
        // server-side (sprint-5/08 AC-08-06/07); any other connection kind
        // ignores/422s it, so a vendor/SQL create never carries the key at
        // all rather than an empty string.
        ...(input.refPrefix ? { refPrefix: input.refPrefix } : {}),
      }),
    });
  },

  updateEntityConfig(companyId, entityType, input) {
    return apiFetch<AutocountEntityConfig>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    );
  },

  syncNow(companyId, entityType) {
    return apiFetch<AutocountSyncJob>(`/autocount/companies/${companyId}/sync`, {
      method: 'POST',
      body: JSON.stringify({ entityType }),
    });
  },

  refetchHistory(companyId, entityType) {
    // BACKEND NEEDED: endpoint not yet implemented (flagged in the interface).
    return apiFetch<AutocountEntityConfig>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/refetch`,
      { method: 'POST' },
    );
  },

  listJobs(query: AutocountJobListQuery = {}) {
    const p = pageParams(query);
    // Default segment = the batches awaiting attention; `all` widens it.
    p.set('status', query.status ?? 'needs_review');
    if (query.entityType) p.set('entityType', query.entityType);
    return apiFetch<ListResult<AutocountSyncJobBatch>>(
      `/autocount/jobs?${p.toString()}`,
    );
  },

  listRuns(companyId, query = {}) {
    const p = pageParams(query);
    if (query.entityType) p.set('entity_type', query.entityType);
    return apiFetch<ListResult<AutocountSyncRun>>(
      `/autocount/companies/${companyId}/runs?${p.toString()}`,
    );
  },

  listStaged(jobId, query = {}) {
    return apiFetch<AutocountStagedList>(
      `/autocount/jobs/${jobId}/staged?${stagedParams(query).toString()}`,
    );
  },

  preview(jobId) {
    return apiFetch<AutocountPreviewResult>(`/autocount/jobs/${jobId}/preview`, {
      method: 'POST',
    });
  },

  approve(jobId) {
    return apiFetch<AutocountApprovalResult>(`/autocount/jobs/${jobId}/approve`, {
      method: 'POST',
    });
  },

  discard(jobId) {
    return apiFetch<AutocountApprovalResult>(`/autocount/jobs/${jobId}/discard`, {
      method: 'POST',
    });
  },

  updateSinkTarget(companyId, input) {
    return apiFetch<AutocountCompany>(
      `/autocount/companies/${companyId}/sink-target`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          sinkImpl: input.sinkImpl,
          sinkConnectionId: input.sinkConnectionId ?? null,
          sorentoCompanyCode: input.sorentoCompanyCode?.trim() || null,
        }),
      },
    );
  },

  getMapping(companyId, entityType) {
    return apiFetch<AutocountMappingView>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping`,
    );
  },

  updateMapping(companyId, entityType, input: AutocountMappingUpdate) {
    return apiFetch<AutocountMappingView>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping`,
      {
        method: 'PUT',
        // `lineRows` omitted (never sent as `undefined`, JSON.stringify
        // drops it) leaves line scope untouched server-side; an explicit
        // `[]` wipes it - the caller (use-mapping-draft) decides which by
        // whether it passes `lineRows` at all (security re-review
        // should-fix, sprint-5/02 review round).
        body: JSON.stringify({
          rows: input.rows.map(writeRow),
          ...(input.lineRows ? { lineRows: input.lineRows.map(writeRow) } : {}),
        }),
      },
    );
  },

  testFormula(companyId, entityType, formula, value) {
    return apiFetch<AutocountFormulaTestResult>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping/test-formula`,
      { method: 'POST', body: JSON.stringify({ formula, value }) },
    );
  },

  simulateMapping(companyId, entityType, record, rows, lines) {
    const body: {
      record: Record<string, unknown>;
      rows?: ReturnType<typeof writeRow>[];
      lines?: Array<Record<string, unknown>>;
    } = { record };
    // Only send `rows` when previewing DRAFT edits; omit to simulate saved rows.
    if (rows) body.rows = rows.map(writeRow);
    // Document entities only (sprint-5/02, AC-02-22) - the picked header's
    // fetched line records.
    if (lines) body.lines = lines;
    return apiFetch<AutocountSimulateResult>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping/simulate`,
      { method: 'POST', body: JSON.stringify(body) },
    );
  },

  listMappingPresets(companyId, entityType) {
    // sprint-5/02 S3 - the mapping editor's "Use preset" action, backed by
    // GET /autocount/presets/{entityType}?companyId= (mounted bare via the
    // `sync` router - see the backend endpoint's own docstring). Real since
    // the S3 mock overlay (withPhase1DocumentMappingMock) was removed.
    return apiFetch<AutocountMappingPreset[]>(
      `/autocount/presets/${encodeURIComponent(entityType)}?companyId=${encodeURIComponent(companyId)}`,
    );
  },

  // ── direct-DB ETL (plan 22 S1) - endpoints per the contract documented on
  // `AutocountService`.

  listSqlConnections() {
    return apiFetch<AutocountSqlConnection[]>('/autocount/sql/connections');
  },

  getSqlSchema(connectionId, opts) {
    const suffix = opts?.refresh ? '?refresh=true' : '';
    return apiFetch<AutocountSqlSchema>(
      `/autocount/sql/connections/${encodeURIComponent(connectionId)}/schema${suffix}`,
    );
  },

  previewSqlQuery(connectionId, query, opts) {
    return apiFetch<AutocountSqlPreview>('/autocount/sql/preview', {
      method: 'POST',
      body: JSON.stringify({
        connectionId,
        query,
        bindDocKey: opts?.bindDocKey ?? false,
        docKey: opts?.docKey ?? null,
      }),
    });
  },

  getEtlTask(companyId, entityType) {
    return apiFetch<AutocountEtlTask>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/etl-task`,
    ).then(normalizeEtlTask);
  },

  updateEtlTask(companyId, entityType, input: AutocountEtlTaskUpdate) {
    return apiFetch<AutocountEtlTask>(
      `${etlTaskPath(companyId, entityType)}`,
      {
        method: 'PUT',
        body: JSON.stringify({
          sourceConfig: input.sourceConfig,
          ...(input.sourceImpl ? { sourceImpl: input.sourceImpl } : {}),
        }),
      },
    ).then(normalizeEtlTask);
  },

  // ── direct-DB ETL (plan 22 S2) - endpoints per the contract documented on
  // `AutocountService`.

  previewEtlTask(companyId, entityType) {
    return apiFetch<AutocountEtlPreviewResult>(`${etlTaskPath(companyId, entityType)}/preview`, {
      method: 'POST',
    }).then((result) => ({ ...result, task: normalizeEtlTask(result.task) }));
  },

  activateEtlTask(companyId, entityType) {
    return apiFetch<AutocountEtlTask>(`${etlTaskPath(companyId, entityType)}/activate`, {
      method: 'POST',
    }).then(normalizeEtlTask);
  },

  pauseEtlTask(companyId, entityType) {
    return apiFetch<AutocountEtlTask>(`${etlTaskPath(companyId, entityType)}/pause`, {
      method: 'POST',
    }).then(normalizeEtlTask);
  },

  resumeEtlTask(companyId, entityType) {
    return apiFetch<AutocountEtlTask>(`${etlTaskPath(companyId, entityType)}/resume`, {
      method: 'POST',
    }).then(normalizeEtlTask);
  },

  runEtlTaskNow(companyId, entityType) {
    return apiFetch<AutocountEtlRunStart>(`${etlTaskPath(companyId, entityType)}/run`, {
      method: 'POST',
    }).then((started) => ({ ...started, task: normalizeEtlTask(started.task) }));
  },

  listEtlRuns(companyId, entityType, query = {}) {
    return apiFetch<ListResult<AutocountSyncRun>>(
      `${etlTaskPath(companyId, entityType)}/runs?${pageParams(query).toString()}`,
    );
  },

  // plan sprint-5/07, AC-07-13..19 - contract documented on `AutocountService`.
  repushEtlTask(companyId, entityType) {
    return apiFetch<AutocountEtlRepushResult>(`${etlTaskPath(companyId, entityType)}/repush`, {
      method: 'POST',
    });
  },

  // sprint-5/08 (S2 backend) - contract documented on `AutocountService`.
  listApiConnections() {
    return apiFetch<AutocountApiConnection[]>('/autocount/http/connections');
  },

  previewHttp(input: HttpPreviewInput) {
    return apiFetch<HttpPreview>('/autocount/http/preview', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
};

/** The per-(company, entity) task resource root. */
function etlTaskPath(companyId: string, entityType: string): string {
  return `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/etl-task`;
}

/** The wire shape of one mapping row on write (a blank formula → null). */
function writeRow(row: AutocountMappingWriteRow) {
  const formula = row.formula?.trim();
  return {
    sourcePath: row.sourcePath,
    transform: row.transform,
    sorentoField: row.sorentoField,
    formula: formula ? formula : null,
    // Default 'header' server-side too (sprint-5/02, AC-02-01) - a
    // master/GRN save never sends anything else.
    scope: row.scope ?? 'header',
    // B1 (final review round) - must round-trip or a backfill-disabled
    // off-preview row is silently re-enabled server-side on save.
    isEnabled: row.isEnabled,
  };
}
