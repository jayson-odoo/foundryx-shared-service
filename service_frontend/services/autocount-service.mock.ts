/**
 * AutoCount ESB mock service (hop 2, plan 14 phase 4) — frontend-first
 * scaffolding behind the service boundary. The real backend is live, so the
 * shipped `autocountService` binds `.real`; this mock exists so the dry-run
 * review states (previewable / not-previewable / failure) are tunable with NO
 * backend, and so the Vitest suite can drive them deterministically.
 *
 * PHASE 1 MOCK — do NOT let a component import this directly. It lives behind
 * `autocount-service.ts`; flip that one line to `mockAutocountService` to build
 * the UI against it, and back to `.real` to ship.
 *
 * Preview state is selected from the `jobId` so every state is reachable
 * without a backend:
 *   - `*logging*` / `*nopreview*`  → not previewable (logging sink)
 *   - `*fail*`                     → the dry run failed (throws HTTP 502)
 *   - anything else                → a realistic previewable payload
 */
import { ApiError } from '@/lib/api-client';
import type {
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyDetail,
  AutocountEntityConfig,
  AutocountJobListQuery,
  AutocountMappingUpdate,
  AutocountMappingView,
  AutocountPreviewResult,
  AutocountSinkTargetInput,
  AutocountStagedList,
  AutocountStagedQuery,
  AutocountStagedRecord,
  AutocountSyncJob,
  AutocountSyncJobBatch,
  AutocountSyncRun,
} from '@/types/autocount';
import type { ListResult } from '@/types/resource';
import type { AutocountService } from './autocount-service';

function mockCompany(overrides: Partial<AutocountCompany> = {}): AutocountCompany {
  return {
    id: 'company-1',
    connectionId: 'conn-autocount-1',
    databaseName: 'AED_VSOFT',
    companyName: 'AED VSoft Sdn Bhd',
    name: 'AED VSoft',
    isActive: true,
    sinkImpl: 'logging',
    sinkConnectionId: null,
    createdAt: '2026-07-01T00:00:00Z',
    ...overrides,
  };
}

function previewablePayload(jobId: string): AutocountPreviewResult {
  return {
    jobId,
    preview: {
      previewable: true,
      sink: 'sorento',
      summary: { total: 172, created: 134, updated: 38, failed: 0, retryable: 0 },
      predictions: [
        // An adoption that BLANKS a live value + overwrites a name — the
        // destructive rows an operator most needs to see.
        {
          sourceRef: 'AED_VSOFT:3',
          outcome: 'updated',
          entityId: 'sup-3',
          changesLiveData: true,
          diff: {
            payment_terms_days: { current: 30, incoming: null },
            customer_name: { current: 'ONE STOP HOME DESIGN', incoming: 'OW PIN BOON' },
          },
          errors: {},
        },
        {
          sourceRef: 'AED_VSOFT:7',
          outcome: 'updated',
          entityId: 'sup-7',
          changesLiveData: true,
          diff: {
            email: { current: 'old@acme.test', incoming: 'billing@acme.test' },
          },
          errors: {},
        },
        // A create — no diff, safe, summarised.
        {
          sourceRef: 'AED_VSOFT:50',
          outcome: 'created',
          entityId: null,
          changesLiveData: false,
          diff: {},
          errors: {},
        },
        {
          sourceRef: 'AED_VSOFT:51',
          outcome: 'created',
          entityId: null,
          changesLiveData: false,
          diff: {},
          errors: {},
        },
      ],
    },
  };
}

function mockName(record: AutocountStagedRecord): string {
  const name = record.canonical?.name;
  return typeof name === 'string' ? name : '';
}

/**
 * A batch with BOTH kinds of staged row — a handful the operator must see
 * (field changes / a failure) and a wall of no-field-change re-fetches — so the
 * paginate + no-change-collapse behaviour (AC-15-10/11) is reachable with no
 * backend.
 */
function mockStagedRecords(): AutocountStagedRecord[] {
  const changed: AutocountStagedRecord[] = [
    {
      id: 'staged-3',
      entityType: 'supplier',
      sourceRef: 'AED_VSOFT:3',
      docNo: '400-J001',
      status: 'STAGED',
      diff: { name: { from: 'ONE STOP HOME DESIGN', to: 'OW PIN BOON' } },
      canonical: { code: '400-J001', name: 'OW PIN BOON', is_active: true },
      errors: null,
      error: null,
      hasChanges: true,
      sourceLastModified: '2026-03-18T08:03:21Z',
    },
    {
      id: 'staged-7',
      entityType: 'supplier',
      sourceRef: 'AED_VSOFT:7',
      docNo: '400-J007',
      status: 'STAGED',
      diff: { email: { from: 'old@acme.test', to: 'billing@acme.test' } },
      canonical: { code: '400-J007', name: 'ACME TRADING', is_active: true },
      errors: null,
      error: null,
      hasChanges: true,
      sourceLastModified: '2026-03-19T02:11:00Z',
    },
    {
      id: 'staged-9',
      entityType: 'supplier',
      sourceRef: 'AED_VSOFT:9',
      docNo: '400-J009',
      status: 'FAILED',
      diff: null,
      canonical: { code: '400-J009', name: 'NO CODE SUPPLIER' },
      errors: [{ field: 'code', message: 'Required field is empty.' }],
      error: null,
      hasChanges: true,
      sourceLastModified: '2026-03-19T04:00:00Z',
    },
  ];
  // 24 legitimate no-op re-fetches — LastModified advanced, no mapped field
  // differs. These must collapse, never bury the three above.
  const noChange: AutocountStagedRecord[] = Array.from({ length: 24 }, (_, i) => ({
    id: `staged-nc-${i}`,
    entityType: 'supplier',
    sourceRef: `AED_VSOFT:${100 + i}`,
    docNo: `400-N${String(i).padStart(3, '0')}`,
    status: 'STAGED' as const,
    diff: {},
    canonical: { code: `400-N${String(i).padStart(3, '0')}`, name: `SUPPLIER ${i}` },
    errors: null,
    error: null,
    hasChanges: false,
    sourceLastModified: '2026-03-20T00:00:00Z',
  }));
  return [...changed, ...noChange];
}

const NOT_IMPLEMENTED = 'Not implemented in the AutoCount mock.';

export const mockAutocountService: AutocountService = {
  listCompanies(): Promise<ListResult<AutocountCompany>> {
    return Promise.resolve({ data: [mockCompany()], total: 1, page: 0 });
  },

  getCompany(id: string): Promise<AutocountCompanyDetail> {
    return Promise.resolve({ company: mockCompany({ id }), entities: [] });
  },

  createCompany(): Promise<AutocountCompany> {
    return Promise.resolve(mockCompany());
  },

  updateEntityConfig(): Promise<AutocountEntityConfig> {
    return Promise.reject(new Error(NOT_IMPLEMENTED));
  },

  syncNow(): Promise<AutocountSyncJob> {
    return Promise.resolve({
      id: 'job-mock',
      status: 'needs_review',
      progressTotal: 172,
      progressDone: 172,
      progressFailed: 0,
      result: null,
      error: null,
      createdAt: '2026-07-21T09:00:00Z',
    });
  },

  listRuns(): Promise<ListResult<AutocountSyncRun>> {
    return Promise.resolve({ data: [], total: 0, page: 0 });
  },

  listJobs(query: AutocountJobListQuery = {}): Promise<ListResult<AutocountSyncJobBatch>> {
    const all: AutocountSyncJobBatch[] = [
      {
        jobId: 'job-1',
        companyId: 'company-1',
        companyName: 'AED VSoft',
        databaseName: 'AED_VSOFT',
        entityType: 'supplier',
        status: 'needs_review',
        progressTotal: 172,
        progressDone: 172,
        progressFailed: 0,
        createdAt: '2026-07-21T09:00:00Z',
        startedAt: '2026-07-21T09:00:01Z',
        finishedAt: '2026-07-21T09:00:12Z',
        updatedAt: '2026-07-21T09:00:12Z',
      },
      {
        jobId: 'job-2',
        companyId: 'company-1',
        companyName: 'AED VSoft',
        databaseName: 'AED_VSOFT',
        entityType: 'customer',
        status: 'done',
        progressTotal: 40,
        progressDone: 40,
        progressFailed: 0,
        createdAt: '2026-07-20T09:00:00Z',
        startedAt: '2026-07-20T09:00:01Z',
        finishedAt: '2026-07-20T09:00:08Z',
        updatedAt: '2026-07-20T09:00:08Z',
      },
    ];
    const status = query.status ?? 'needs_review';
    const matched = status === 'all' ? all : all.filter((j) => j.status === status);
    const page = query.page ?? 0;
    const pageSize = query.pageSize ?? 25;
    return Promise.resolve({
      data: matched.slice(page * pageSize, page * pageSize + pageSize),
      total: matched.length,
      page,
    });
  },

  listStaged(jobId: string, query: AutocountStagedQuery = {}): Promise<AutocountStagedList> {
    const all = mockStagedRecords();
    const term = (query.search ?? '').trim().toLowerCase();
    let matched = all;
    if (query.changed === true) matched = matched.filter((r) => r.hasChanges);
    else if (query.changed === false) matched = matched.filter((r) => !r.hasChanges);
    if (query.status) matched = matched.filter((r) => r.status === query.status);
    if (term) {
      matched = matched.filter((r) =>
        [r.sourceRef, r.docNo, mockName(r)]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(term)),
      );
    }
    const page = query.page ?? 0;
    const pageSize = query.pageSize ?? 25;
    const start = page * pageSize;
    return Promise.resolve({
      job: {
        id: jobId,
        status: 'needs_review',
        progressTotal: all.length,
        progressDone: all.length,
        progressFailed: all.filter((r) => r.status === 'FAILED').length,
        result: null,
        error: null,
        createdAt: '2026-07-21T09:00:00Z',
      },
      data: matched.slice(start, start + pageSize),
      total: matched.length,
      noChangeCount: all.filter((r) => !r.hasChanges).length,
    });
  },

  refetchHistory(_companyId, entityType): Promise<AutocountEntityConfig> {
    return Promise.resolve({
      id: 'e-mock',
      entityType,
      syncMode: 'SCHEDULED_REVIEW',
      sourceImpl: 'autocount_read',
      recordCap: 200,
      initialLookbackDays: 30,
      enabled: true,
      lastSuccessAt: null,
      lastAttemptAt: null,
      watermarkAt: null, // the reset — the first-run window is live again
      consecutiveFailures: 0,
      lastError: null,
    });
  },

  preview(jobId: string): Promise<AutocountPreviewResult> {
    if (jobId.includes('logging') || jobId.includes('nopreview')) {
      return Promise.resolve({
        jobId,
        preview: {
          previewable: false,
          sink: 'logging',
          reason:
            'No consumer is configured for this company, so there is nothing to preview.',
        },
      });
    }
    if (jobId.includes('fail')) {
      return Promise.reject(
        new ApiError(
          'The dry run against the consumer failed, so this batch cannot be approved yet. Nothing was written — resolve the consumer error first.',
          502,
        ),
      );
    }
    return Promise.resolve(previewablePayload(jobId));
  },

  approve(jobId: string): Promise<AutocountApprovalResult> {
    return Promise.resolve({ jobId, result: { pushed: 172 } });
  },

  discard(jobId: string): Promise<AutocountApprovalResult> {
    return Promise.resolve({ jobId, result: { discarded: 172 } });
  },

  updateSinkTarget(
    companyId: string,
    input: AutocountSinkTargetInput,
  ): Promise<AutocountCompany> {
    return Promise.resolve(
      mockCompany({
        id: companyId,
        sinkImpl: input.sinkImpl,
        sinkConnectionId: input.sinkImpl === 'sorento' ? input.sinkConnectionId ?? null : null,
      }),
    );
  },

  getMapping(_companyId: string, entityType: string): Promise<AutocountMappingView> {
    return Promise.resolve(mockMappingView(entityType));
  },

  updateMapping(
    _companyId: string,
    entityType: string,
    input: AutocountMappingUpdate,
  ): Promise<AutocountMappingView> {
    // A required Sorento target left unmapped is the real failure the editor
    // guards; a target outside the accepted set is a 422 server-side. The mock
    // rejects an unknown target so the surfaced-error path is testable.
    const view = mockMappingView(entityType);
    const accepted = new Set(view.sorentoFields.map((f) => f.field));
    for (const row of input.rows) {
      if (!accepted.has(row.sorentoField)) {
        return Promise.reject(
          new ApiError(
            `'${row.sorentoField}' is not a Sorento field accepted for ${entityType}.`,
            422,
          ),
        );
      }
    }
    return Promise.resolve({
      ...view,
      rows: input.rows.map((row) => ({
        sourcePath: row.sourcePath,
        transform: row.transform,
        sorentoField: row.sorentoField,
        canonicalField: row.sorentoField,
        scope: 'header',
        isRequired: view.sorentoFields.find((f) => f.field === row.sorentoField)?.required ?? false,
        isEnabled: true,
      })),
    });
  },
};

/** A realistic supplier/customer mapping view for the editor's tunable states. */
function mockMappingView(entityType: string): AutocountMappingView {
  return {
    entityType,
    rows: [
      {
        sourcePath: 'AccNo',
        transform: 'string',
        sorentoField: 'code',
        canonicalField: 'code',
        scope: 'header',
        isRequired: true,
        isEnabled: true,
      },
      {
        sourcePath: 'CompanyName',
        transform: 'string',
        sorentoField: 'name',
        canonicalField: 'name',
        scope: 'header',
        isRequired: true,
        isEnabled: true,
      },
      {
        sourcePath: 'IsActive',
        transform: 't_f_bool',
        sorentoField: 'is_active',
        canonicalField: 'is_active',
        scope: 'header',
        isRequired: true,
        isEnabled: true,
      },
      {
        sourcePath: 'EmailAddress',
        transform: 'string',
        sorentoField: 'email',
        canonicalField: 'email',
        scope: 'header',
        isRequired: false,
        isEnabled: true,
      },
      // A provenance row — stored canonically, never delivered to Sorento.
      {
        sourcePath: 'Data.0.LastModified',
        transform: 'slash_datetime',
        sorentoField: null,
        canonicalField: 'last_modified',
        scope: 'header',
        isRequired: false,
        isEnabled: true,
      },
    ],
    sorentoFields: [
      { field: 'code', required: true },
      { field: 'name', required: true },
      { field: 'is_active', required: true },
      { field: 'email', required: false },
      { field: 'phone_number', required: false },
      { field: 'tax_id', required: false },
    ],
    acFields: [
      'AccNo',
      'CompanyName',
      'EmailAddress',
      'IsActive',
      'Mobile',
      'TIN',
      'Data.0.AutoKey',
      'Data.0.LastModified',
    ],
  };
}
