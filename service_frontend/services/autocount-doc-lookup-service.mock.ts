/**
 * Frontend-first mock + Vitest double for the AutoCount document finder
 * (sprint-5/17). NOT bound by the barrel - the shipped binding is `.real`.
 * Deterministic: `PS202610-0004` is the re-dated case (snapshot said
 * 2026-10-01, AutoCount now says 2026-10-05, found by last-modified);
 * any other number is not found.
 */
import type {
  DocLookupJob,
  DocLookupResult,
  DocLookupSettings,
  DocLookupStartInput,
  DocLookupStep,
  DocLookupStored,
  DocLookupType,
} from '@/types/autocount-doc-lookup';
import type { AutocountDocLookupService } from './autocount-doc-lookup-service';

export const MOCK_REDATED_DOC_NO = 'PS202610-0004';

const TYPES: DocLookupType[] = [
  { key: 'delivery_order', label: 'Delivery order', prefixes: ['PS', 'DO'], hasLastModified: true, hasByDocNo: false, connected: null },
  { key: 'goods_receive_note', label: 'Goods received note', prefixes: ['GRN', 'GR'], hasLastModified: true, hasByDocNo: false, connected: null },
];

function detect(docNo: string): string {
  const upper = docNo.trim().toUpperCase();
  return upper.startsWith('GR') ? 'goods_receive_note' : 'delivery_order';
}

function isRedated(docNo: string): boolean {
  return docNo.trim().toUpperCase() === MOCK_REDATED_DOC_NO;
}

function shiftDay(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const MOCK_TODAY = '2026-10-01';

function notFoundSteps(): DocLookupStep[] {
  const steps: DocLookupStep[] = [];
  for (let i = 0; i <= 7; i += 1) {
    steps.push({ door: 'by_last_modified', day: shiftDay(MOCK_TODAY, -i), status: 'miss', count: 3 });
  }
  for (let i = 0; i <= 14; i += 1) {
    steps.push({ door: 'by_doc_date', day: shiftDay(MOCK_TODAY, i), status: 'miss', count: 3 });
  }
  return steps;
}

function redatedResult(docNo: string): DocLookupResult {
  return {
    docType: 'delivery_order',
    docNo,
    found: true,
    current: {
      docKey: 55731,
      docNo: MOCK_REDATED_DOC_NO,
      docDate: '2026-10-05',
      lastModified: '2026-10-01T07:39:22.000',
      lastModifiedBy: 'AIN',
      cancelled: false,
      header: {
        DocKey: 55731, DocNo: MOCK_REDATED_DOC_NO, DocDate: '2026-10-05T00:00:00',
        DebtorCode: '300-R009', DebtorName: 'Anon Trading Sdn Bhd', Ref: 'Anon iP-001241',
        CurrencyCode: 'MYR', NetTotal: 1250, Cancelled: 'F',
        LastModified: '2026-10-01T07:39:22.000', LastModifiedUserID: 'AIN',
      },
      lines: [
        { Seq: 1, ItemCode: 'ACC-CB8001', Description: 'Anon circular breaker', UOM: 'PCS', Qty: 10, UnitPrice: 25, SubTotal: 250 },
        { Seq: 2, ItemCode: 'ACC-SW2002', Description: 'Anon wall switch 2-gang', UOM: 'PCS', Qty: 40, UnitPrice: 12.5, SubTotal: 500 },
        { Seq: 3, ItemCode: 'ACC-CL0300', Description: 'Anon cable 2.5mm 100m', UOM: 'ROLL', Qty: 2, UnitPrice: 250, SubTotal: 500 },
      ],
    },
    foundBy: { door: 'by_last_modified', day: '2026-10-01' },
    redated: { from: '2026-10-01', to: '2026-10-05', source: 'snapshot' },
    steps: [
      { door: 'by_doc_date', day: '2026-10-01', status: 'miss', count: 12 },
      { door: 'by_last_modified', day: '2026-10-01', status: 'hit', count: 9 },
    ],
    searched: {
      lastModifiedFrom: '2026-09-24', lastModifiedTo: '2026-10-01',
      docDateFrom: '2026-10-01', docDateTo: '2026-10-15',
    },
  };
}

function notFoundResult(docNo: string): DocLookupResult {
  return {
    docType: detect(docNo),
    docNo,
    found: false,
    current: null,
    foundBy: null,
    redated: null,
    steps: notFoundSteps(),
    searched: {
      lastModifiedFrom: '2026-09-24', lastModifiedTo: '2026-10-01',
      docDateFrom: '2026-10-01', docDateTo: '2026-10-15',
    },
  };
}

const jobs = new Map<string, DocLookupJob>();
const settings = new Map<string, DocLookupSettings>();
let seq = 0;

export function resetMockDocLookup(): void {
  jobs.clear();
  settings.clear();
  seq = 0;
}

export const mockAutocountDocLookupService: AutocountDocLookupService = {
  async listTypes(companyId?: string | null) {
    // Mock wiring: every company has a delivery-order connection, none for GRN.
    return TYPES.map((t) => ({
      ...t,
      connected: companyId ? t.key === 'delivery_order' : null,
    }));
  },

  async stored(_companyId, docNo, docType) {
    const result: DocLookupStored = {
      docType: docType || detect(docNo),
      docNo: docNo.trim(),
      snapshots: isRedated(docNo)
        ? [{
            snapshotId: 'c41e00000000000000000000009a2', createdAt: '2026-09-30T22:10:00Z',
            extractedAt: '2026-09-30T22:10:00Z', fromDay: '2026-10-01', toDay: '2026-10-01',
            byNumber: false, docKey: 55731, docDate: '2026-10-01',
            lastModified: '2026-09-30T18:02:00.000', cancelled: false,
          }]
        : [],
      ledger: null,
    };
    return result;
  },

  async start(input: DocLookupStartInput) {
    seq += 1;
    const result = isRedated(input.docNo) ? redatedResult(input.docNo.trim()) : notFoundResult(input.docNo.trim());
    const job: DocLookupJob = {
      jobId: `mock-lookup-${seq}`, status: 'done', companyId: input.companyId,
      docNo: input.docNo.trim(), docType: result.docType,
      progressDone: result.steps.length, progressTotal: result.steps.length, result,
      error: null, createdAt: '2026-10-01T00:00:00Z', finishedAt: '2026-10-01T00:00:05Z',
    };
    jobs.set(job.jobId, job);
    return job;
  },

  async getJob(jobId: string) {
    const job = jobs.get(jobId);
    if (!job) throw new Error('Document search not found.');
    return job;
  },

  async stop(jobId: string) {
    const job = await this.getJob(jobId);
    const stopped: DocLookupJob = { ...job, status: 'aborted' };
    jobs.set(jobId, stopped);
    return stopped;
  },

  async getSettings(companyId: string) {
    return settings.get(companyId) ?? { companyId, lastModifiedBackDays: 7, docDateForwardDays: 14 };
  },

  async saveSettings(input: DocLookupSettings) {
    settings.set(input.companyId, input);
    return input;
  },
};
