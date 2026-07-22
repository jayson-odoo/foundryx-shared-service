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
  AutocountPreviewResult,
  AutocountSinkTargetInput,
  AutocountStagedList,
  AutocountSyncJob,
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

  listStaged(jobId: string): Promise<AutocountStagedList> {
    return Promise.resolve({
      job: {
        id: jobId,
        status: 'needs_review',
        progressTotal: 172,
        progressDone: 172,
        progressFailed: 0,
        result: null,
        error: null,
        createdAt: '2026-07-21T09:00:00Z',
      },
      data: [
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
          sourceLastModified: '2026-03-18T08:03:21Z',
        },
      ],
      total: 1,
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
};
