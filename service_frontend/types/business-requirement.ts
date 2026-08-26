/**
 * Business Requirement types (Phase B-i slice 2, AC-BI-15..19) - the FE side of
 * the ideation BR backend contract (modules/ideation/schemas.py). A BR is the
 * second stage of the pipeline (Idea → BR → FR → delivery); its `answers` render
 * through the form-engine renderer against its STAMPED template doc.
 */
import type { FormAnswers, FormDocument } from '@/types/forms';

/** BR lifecycle keys (mirror the seeded status graph, AC-BI-15). */
export type BusinessRequirementStatus =
  | 'draft'
  | 'grilling'
  | 'ready'
  | 'in_fr'
  | 'delivered'
  | 'archived';

/** One BR row (list) / detail base. `status` is the lifecycle KEY; the label +
 * color are server-rendered (never branch on the label). */
export interface BusinessRequirement {
  id: string;
  productId: string;
  productName: string;
  status: string;
  statusLabel: string;
  statusColor: string;
  templateKey: string;
  templateVersion: number;
  title: string;
  ideaCount: number;
  createdAt: string;
  updatedAt: string;
}

/** BR detail - adds the answer map + the STAMPED template block document. */
export interface BusinessRequirementDetail extends BusinessRequirement {
  answers: FormAnswers;
  templateDoc: FormDocument;
}

/** One BR-template version (Versions tab). `isStamped` marks the version this BR
 * renders against forever (AC-BI-16). */
export interface BrTemplateVersion {
  version: number;
  isStamped: boolean;
  isActive: boolean;
  createdAt: string;
}

/** Create a draft BR against a product; `answers` validate against the stamped
 * version, `ideaIds` optionally links same-product ideas. */
export interface BusinessRequirementCreateInput {
  productId: string;
  title?: string;
  answers?: FormAnswers;
  ideaIds?: string[];
}

/** Partial edit - title and/or answers (validated against the stamped version). */
export interface BusinessRequirementUpdateInput {
  title?: string;
  answers?: FormAnswers;
}
