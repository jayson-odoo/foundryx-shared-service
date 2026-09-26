/**
 * Business Requirement service - the boundary the BR UI talks to (Phase B-i
 * slice 2). The interface IS the backend contract
 * (modules/ideation/routers/business_requirements.py).
 *
 * Enforced layering: UI → hooks → this service → lib/api-client → FastAPI.
 * Frontend-first built against `.mock`; the boundary is swapped to `.real`
 * below (the ONE line). The mock is retained only for tests.
 */
import type { Idea } from '@/types/ideation';
import type { StatusGraph } from '@/types/status-engine';
import type {
  BrTemplateVersion,
  BusinessRequirement,
  BusinessRequirementCreateInput,
  BusinessRequirementDetail,
  BusinessRequirementStatus,
  BusinessRequirementUpdateInput,
} from '@/types/business-requirement';
import { realBusinessRequirementService } from './business-requirement-service.real';

export interface BrListFilter {
  search?: string;
  filter?: 'active' | 'archived' | 'all';
  productId?: string;
  /** Include test Business Requirements (issue #90 W3) - off by default; the
   * BR list exposes a "Show test requirements" toggle that flips this. */
  includeTest?: boolean;
}

/** Whether an active Business Requirement template is configured (issue #90
 * W2) - the "New business requirement" dialog reads this before offering
 * Create so a user never round-trips the `br_template_unavailable` 422. */
export interface BrTemplateStatus {
  active: boolean;
}

export interface BusinessRequirementService {
  /** All BRs for the tenant, newest first. */
  list(params?: BrListFilter): Promise<BusinessRequirement[]>;
  /** One BR by id (detail - answers + stamped template doc). Rejects if absent. */
  get(id: string): Promise<BusinessRequirementDetail>;
  /** Create a draft BR (stamps the active template version). */
  create(input: BusinessRequirementCreateInput): Promise<BusinessRequirementDetail>;
  /** Edit title / answers (validated against the stamped version). */
  update(
    id: string,
    input: BusinessRequirementUpdateInput,
  ): Promise<BusinessRequirementDetail>;
  /** Move to a lifecycle status by key (server-authoritative). */
  setStatus(
    id: string,
    status: BusinessRequirementStatus,
  ): Promise<BusinessRequirementDetail>;
  /** The BR entity's status graph - backs the detail form's lifecycle/promote
   * action registry (AC-BI-34). Gated ideation.business_requirements.read. */
  statusGraph(): Promise<StatusGraph>;
  /** The Ideas feeding this BR (lineage). */
  listIdeas(id: string): Promise<Idea[]>;
  /** The BRs an idea feeds (reverse lineage) - backs the idea detail's Business
   * Requirements tab (AC-BI-29c). */
  listForIdea(ideaId: string): Promise<BusinessRequirement[]>;
  /** Link ideas to the BR (same product). Returns the new linked set. */
  linkIdeas(id: string, ideaIds: string[]): Promise<Idea[]>;
  /** Unlink one idea. Returns the remaining linked set. */
  unlinkIdea(id: string, ideaId: string): Promise<Idea[]>;
  /** The BR's template version history (Versions tab). */
  listVersions(id: string): Promise<BrTemplateVersion[]>;
  /** Delete a BR. */
  remove(id: string): Promise<void>;
  /** Whether an active BR template is configured (issue #90 W2) - read by the
   * create dialog before offering Create. Gated
   * `ideation.business_requirements.read`. */
  templateStatus(): Promise<BrTemplateStatus>;
}

export const businessRequirementService: BusinessRequirementService =
  realBusinessRequirementService;
