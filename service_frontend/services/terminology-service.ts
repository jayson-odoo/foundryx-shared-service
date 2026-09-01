/**
 * Terminology service (sprint-3/08, F10) - the boundary the terminology
 * surfaces talk to (via the hook). Phase A binds the mock; Phase B swaps to the
 * real api-client impl in ONE line (bottom). The interface IS the backend
 * contract (plan 08).
 */
import type { TermCatalogItem, TermLabels, TerminologyMap } from '@/types/terminology';
import { realTerminologyService } from './terminology-service.real';

export interface TerminologyService {
  /** Merged map (defaults ⊕ tenant overrides) - the client-cache source. */
  getTerminology(): Promise<TerminologyMap>;
  /** All registered TermDefs + current overrides (drives the settings page). */
  getCatalog(): Promise<TermCatalogItem[]>;
  /** Upsert an override (both forms required). 422 on unknown key. */
  setTerm(key: string, labels: TermLabels): Promise<TermLabels>;
  /** Reset to the code default (delete the override row). */
  resetTerm(key: string): Promise<void>;
}

// Phase B: real api-client. (Mock retained in terminology-service.mock.ts.)
export const terminologyService: TerminologyService = realTerminologyService;
