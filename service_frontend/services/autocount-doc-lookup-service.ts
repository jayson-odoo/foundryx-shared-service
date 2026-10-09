/**
 * AutoCount document finder service (sprint-5/17) - the boundary
 * `/autocount/find` talks to via `hooks/use-autocount-doc-lookup`. The
 * interface IS the backend contract (`modules/autocount/routers/doc_lookup.py`,
 * prefix `/autocount/doc-lookup`, gated `autocount.pull.read`; saving the
 * windows needs `autocount.companies.manage`). Read only towards AutoCount.
 *
 * Binds the REAL implementation; the `.mock` sibling is the frontend-first
 * scaffolding + Vitest double (house service-trio pattern).
 */
import type {
  DocLookupJob,
  DocLookupSettings,
  DocLookupStartInput,
  DocLookupStored,
  DocLookupType,
} from '@/types/autocount-doc-lookup';
import { realAutocountDocLookupService } from './autocount-doc-lookup-service.real';

export interface AutocountDocLookupService {
  /** With `companyId`, each type carries `connected` for that company. */
  listTypes(companyId?: string | null): Promise<DocLookupType[]>;
  /** Snapshot + feed-ledger sightings - zero AutoCount calls. */
  stored(companyId: string, docNo: string, docType?: string | null): Promise<DocLookupStored>;
  /** Start (or re-attach to) the live search job. */
  start(input: DocLookupStartInput): Promise<DocLookupJob>;
  getJob(jobId: string): Promise<DocLookupJob>;
  stop(jobId: string): Promise<DocLookupJob>;
  getSettings(companyId: string): Promise<DocLookupSettings>;
  saveSettings(input: DocLookupSettings): Promise<DocLookupSettings>;
}

export const autocountDocLookupService: AutocountDocLookupService = realAutocountDocLookupService;
