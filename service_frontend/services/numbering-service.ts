/**
 * Numbering service (sprint-4/07, Cluster F) - the boundary the numbering
 * settings surface talks to (via the page/dialog). The interface IS the backend
 * contract. The real api-client impl is wired below (backend exists this slice).
 */
import type { NumberCatalogItem, NumberFormatSet } from '@/types/numbering';
import { realNumberingService } from './numbering-service.real';

export interface NumberingService {
  /** The numbering catalog (defaults ⊕ overrides ⊕ live next-val). */
  getCatalog(): Promise<NumberCatalogItem[]>;
  /** Upsert a format override (prefix / format / reset). 422 on unknown type. */
  setFormat(docType: string, body: NumberFormatSet): Promise<void>;
  /** Set the next running value for the current period. */
  setNextVal(docType: string, nextVal: number): Promise<void>;
  /** Reset to the registered default (delete the override row). */
  resetFormat(docType: string): Promise<void>;
}

// Real api-client. (Mock retained in numbering-service.mock.ts for unit tests.)
export const numberingService: NumberingService = realNumberingService;
