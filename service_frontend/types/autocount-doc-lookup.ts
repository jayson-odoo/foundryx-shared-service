/**
 * AutoCount document finder (sprint-5/17, AC-DOC-FINDER) - the wire shapes of
 * `modules/autocount/routers/doc_lookup.py`. Vendor values (`docDate`,
 * `lastModified`) are AutoCount's own wall-clock strings, never UTC instants;
 * `createdAt`/`pushedAt`/... are Z-suffixed system timestamps.
 */

export interface DocLookupType {
  key: string;
  label: string;
  prefixes: string[];
  hasLastModified: boolean;
  hasByDocNo: boolean;
  /** With `companyId`: does the company have an AutoCount connection for
   * this type? `null` when no company was given. */
  connected: boolean | null;
}

export interface DocLookupSnapshotSighting {
  snapshotId: string;
  createdAt: string | null;
  extractedAt: string | null;
  fromDay: string | null;
  toDay: string | null;
  byNumber: boolean;
  docKey: number | null;
  docDate: string | null;
  lastModified: string | null;
  cancelled: boolean;
}

export interface DocLookupLedgerSighting {
  docKey: number | null;
  docDate: string | null;
  sourceModifiedAt: string | null;
  lastOutcome: string | null;
  pushedAt: string | null;
  vanishedAt: string | null;
}

export interface DocLookupStored {
  docType: string;
  docNo: string;
  snapshots: DocLookupSnapshotSighting[];
  ledger: DocLookupLedgerSighting | null;
}

export type DocLookupDoor = 'by_doc_date' | 'by_last_modified';
export type DocLookupStepStatus = 'pending' | 'hit' | 'miss' | 'error' | 'skipped';

export interface DocLookupStep {
  door: DocLookupDoor;
  day: string;
  status: DocLookupStepStatus;
  count: number | null;
  error?: string;
}

export type DocLookupVendorValue = string | number | boolean | null | DocLookupVendorValue[] | {
  [key: string]: DocLookupVendorValue;
};

export type DocLookupVendorRecord = Record<string, DocLookupVendorValue>;

export interface DocLookupCurrent {
  docKey: number | null;
  docNo: string | null;
  docDate: string | null;
  lastModified: string | null;
  lastModifiedBy: string | null;
  cancelled: boolean;
  header: DocLookupVendorRecord;
  lines: DocLookupVendorRecord[];
}

export interface DocLookupResult {
  docType: string;
  docNo: string;
  found: boolean;
  current: DocLookupCurrent | null;
  foundBy: { door: DocLookupDoor; day: string } | null;
  redated: { from: string; to: string; source: 'snapshot' | 'ledger' | 'hint' } | null;
  steps: DocLookupStep[];
  searched: {
    lastModifiedFrom: string | null;
    lastModifiedTo: string | null;
    docDateFrom: string;
    docDateTo: string;
  };
}

export type DocLookupJobStatus = 'pending' | 'running' | 'done' | 'failed' | 'aborted' | 'needs_review';

export interface DocLookupJob {
  jobId: string;
  status: DocLookupJobStatus;
  companyId: string | null;
  docNo: string | null;
  docType: string | null;
  progressDone: number;
  progressTotal: number;
  result: DocLookupResult | null;
  error: string | null;
  createdAt: string | null;
  finishedAt: string | null;
}

export interface DocLookupStartInput {
  companyId: string;
  docNo: string;
  docType?: string | null;
  aroundDay?: string | null;
}

export interface DocLookupSettings {
  companyId: string;
  lastModifiedBackDays: number;
  docDateForwardDays: number;
}
