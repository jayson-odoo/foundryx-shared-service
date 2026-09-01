/**
 * Form engine wire contracts (plan sprint-3/01). `FormDocument` is the
 * forever-contract block document - `schemaVersion` at root, Page → Section →
 * Field (D6), editor-agnostic, NEVER stored compiled. Mirrors the backend
 * `app/form_engine/schemas.py` (Phase B; parity-pinned like branding tokens).
 * All datetimes are Z-suffixed UTC strings (ApiModel); render via
 * `useDatetime`.
 */

import type { RuleGroup } from './rules';

export const FORM_SCHEMA_VERSION = 1;

// ---- field taxonomy (D7 - full v1, `payment` deferred BL-086) ----

/** Answer-bearing field types. */
export type FormInputFieldType =
  | 'text'
  | 'textarea'
  | 'email'
  | 'phone'
  | 'url'
  | 'number'
  | 'integer'
  | 'select'
  | 'multiselect'
  | 'radio'
  | 'checkboxes'
  | 'yesno'
  | 'date'
  | 'datetime'
  | 'file'
  | 'signature'
  | 'rating'
  | 'address'
  | 'repeater'
  | 'table'
  | 'computed';

/** Display-only field types - render, collect nothing. */
export type FormDisplayFieldType = 'heading' | 'paragraph' | 'divider';

export type FormFieldType = FormInputFieldType | FormDisplayFieldType;

/** Sub-field types a repeater row may carry (no composites/uploads/display -
 * conditions on sub-fields = BL-089). */
export type FormSubFieldType =
  | 'text'
  | 'textarea'
  | 'email'
  | 'phone'
  | 'url'
  | 'number'
  | 'select'
  | 'radio'
  | 'yesno'
  | 'date'
  | 'rating';

// ---- choice options (D8 - static-only v1, `entity` slots in via BL-087) ----

export interface FormChoiceItem {
  value: string;
  label: string;
}

export interface FormStaticOptions {
  kind: 'static';
  items: FormChoiceItem[];
}

/** Shaped for additive growth: `{kind:'entity', …}` lands without doc break. */
export type FormChoiceOptions = FormStaticOptions;

// ---- per-type validation config ----

/** Text-family constraints (`text`/`textarea`/`email`/`phone`/`url`). */
export interface FormTextValidation {
  minLength?: number;
  maxLength?: number;
  /** Anchored ECMAScript-compatible regex source (no flags). */
  pattern?: string;
  /** Shown when `pattern` rejects - required alongside it. */
  patternMessage?: string;
}

export interface FormNumberValidation {
  min?: number;
  max?: number;
  step?: number;
  /** Display + input precision (decimal places). Drives formatting + a
   * max-decimal-places validation (decimal mode only). */
  decimals?: number;
  /** Whole numbers only (age, qty) - rejects any fraction. Default = decimal. */
  integer?: boolean;
}

export interface FormFileValidation {
  /** Per-file cap in megabytes. */
  maxSizeMb?: number;
  /** Sniffed-mime whitelist (e.g. `application/pdf`, `image/png`). */
  allowedMimes?: string[];
  /** Max files on this field. */
  maxCount?: number;
}

// ---- the document tree (D6) ----

/** One leaf of the form. `key` is the STABLE answer key - relabel never
 * breaks refs (workflow-node-id precedent); unique across the doc. Display
 * fields carry no `key`/`required`. Type-specific config rides the optional
 * bags - the publish gate (`validate_form_doc`) enforces which bag belongs
 * to which type. */
export interface FormField {
  id: string;
  type: FormFieldType;
  /** Answer key - required for input types, absent for display types. */
  key?: string;
  /** Field label; for `heading` the heading text, for `paragraph` the body. */
  label: string;
  required?: boolean;
  placeholder?: string;
  helpText?: string;
  /** Rule-engine visibility - facts namespace `answers.<fieldKey>`, EARLIER
   * fields only (document order - publish-gate enforced, D14). */
  conditionsJson?: RuleGroup | null;

  // -- type-specific bags (exactly one applies, per type) --
  text?: FormTextValidation;
  number?: FormNumberValidation;
  /** `select`/`multiselect`/`radio`/`checkboxes`. */
  options?: FormChoiceOptions;
  file?: FormFileValidation;
  /** `rating`: 1-N scale. */
  rating?: { max: number };
  /** `heading`: visual level. */
  heading?: { level: 1 | 2 | 3 };
  /** `repeater`: author-defined row shape + row count bounds. */
  repeater?: {
    fields: FormSubField[];
    minRows?: number;
    maxRows?: number;
  };
  /** `computed`: arithmetic-only expression over sibling field keys
   * (`qty * unitPrice`) - own parser, never eval (anti-SSTI). */
  computed?: { expression: string };
  /** `table`: tabular line items (PO/SO/invoice) - authored columns, per-row
   * computed columns, column totals, optional row numbers. */
  table?: FormTableConfig;
}

/** One column of a Table block. `computed` columns are read-only and evaluated
 * PER ROW over that row's earlier columns (`qty * unitPrice`). `summarize` adds
 * a column total to the table footer. */
export interface FormTableColumn {
  id: string;
  key: string;
  label: string;
  type: 'text' | 'number' | 'integer' | 'select' | 'date' | 'computed' | 'fixed';
  required?: boolean;
  placeholder?: string;
  options?: FormChoiceOptions;
  number?: FormNumberValidation;
  computed?: { expression: string };
  summarize?: FormSummarize;
  /** Display precision (decimal places) for number/computed/fixed columns. */
  decimals?: number;
  /** Whole numbers only for a number column (decimals ignored). */
  integer?: boolean;
  /** `fixed`: the constant value stamped into every row (read-only). */
  fixedValue?: string;
}

export interface FormTableConfig {
  columns: FormTableColumn[];
  /** Show a leading row-number (#) column. */
  showRowNumbers?: boolean;
  minRows?: number;
  maxRows?: number;
}

/** A repeater row's sub-field - restricted type set, no conditions (BL-089). */
/** Column-summary technique for a Table column total footer (sprint-3/02).
 * `count` works on any column; the rest need a numeric column. */
export type FormSummarize = 'sum' | 'avg' | 'count' | 'min' | 'max';

export interface FormSubField {
  id: string;
  type: FormSubFieldType;
  key: string;
  label: string;
  required?: boolean;
  placeholder?: string;
  text?: FormTextValidation;
  number?: FormNumberValidation;
  options?: FormChoiceOptions;
  rating?: { max: number };
}

/** Titled group; optional 2-column layout; conditionally visible. */
export interface FormSection {
  id: string;
  title?: string;
  description?: string;
  twoColumn?: boolean;
  conditionsJson?: RuleGroup | null;
  fields: FormField[];
}

/** Wizard step - per-page client validation before advancing. */
export interface FormPage {
  id: string;
  title?: string;
  sections: FormSection[];
}

export interface FormDocument {
  schemaVersion: number;
  pages: FormPage[];
}

// ---- answers ----

/** `address` composite answer (sub-key whitelist enforced server-side). */
export interface FormAddressAnswer {
  line1?: string;
  line2?: string;
  city?: string;
  state?: string;
  postcode?: string;
  /** ISO 3166-1 alpha-2. */
  country?: string;
}

/** One uploaded file as stored - quarantined storage key, display name. */
export interface FormFileAnswer {
  key: string;
  name: string;
  size: number;
  mime: string;
}

export type FormAnswerScalar = string | number | boolean | null;

export type FormAnswerValue =
  | FormAnswerScalar
  | string[]
  | FormAddressAnswer
  | FormFileAnswer[]
  | Record<string, FormAnswerScalar>[];

export type FormAnswers = Record<string, FormAnswerValue>;

/** 422 contract (D14): per-field error map → inline highlight + jump-to-page. */
export type FormFieldErrors = Record<string, string>;

// ---- wire entities ----

export type FormDefinitionStatus = 'draft' | 'published' | 'archived';

/** `portal` reserved for Cluster D (D11). */
export type FormAccess = 'internal' | 'public';

export interface FormRow {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  status: FormDefinitionStatus;
  access: FormAccess;
  /** Archived view membership (shell Active|Archived contract). */
  isTrashed: boolean;
  currentVersionId: string | null;
  currentVersionNumber: number | null;
  /** Draft differs from the published snapshot (toolbar "unpublished changes"). */
  hasUnpublishedChanges: boolean;
  opensAt: string | null;
  closesAt: string | null;
  maxSubmissions: number | null;
  submissionLimitPerUser: number | null;
  /** Field keys pinned as Submissions-list columns (D18). */
  pinnedColumns: string[];
  /** Render pages as wizard steps or one scrolling page (Settings, D18). */
  displayMode: 'paged' | 'single';
  /** Authors may revise a frozen submission into a new immutable snapshot
   * (plan sprint-4/04). */
  allowRevisions: boolean;
  submissionCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface FormDetail extends FormRow {
  draftDefinition: FormDocument;
}

export interface FormVersionRow {
  id: string;
  versionNumber: number;
  publishedBy: string | null;
  publishedByName: string | null;
  createdAt: string;
}

export interface FormSubmissionRow {
  id: string;
  formId: string;
  /** Stable identity across revisions; external refs point here, resolve to
   * the `isCurrent` row (plan sprint-4/04 R1). Equals `id` for originals. */
  submissionGroupId: string;
  /** 1-based; increments per revision within a group (R1). */
  revisionNumber: number;
  /** Flags the live revision of its group; lists default to this (R1/R3). */
  isCurrent: boolean;
  versionId: string;
  versionNumber: number;
  statusId: string;
  statusKey: string;
  statusLabel: string;
  statusColor: string;
  /** NULL = anonymous (public surface, slice 2). */
  userId: string | null;
  userName: string | null;
  subjectType: string | null;
  subjectId: string | null;
  answers: FormAnswers;
  submittedAt: string | null;
  createdAt: string;
  updatedAt: string;
  /** Per-record fireable transition ids (graph-driven buttons). */
  availableTransitionIds?: string[] | null;
}

/** Read-model for fill surfaces - the PUBLISHED version only (D9). */
export interface FormFillView {
  formId: string;
  versionId: string;
  versionNumber: number;
  name: string;
  description: string | null;
  definition: FormDocument;
  /** Single page = no wizard chrome (Settings paged-vs-single, D18). */
  paged: boolean;
}

/** The serving state of a public form (slice 2, D10/D11). `open` carries the
 * definition to fill; `closed`/`full` render a friendly message with no schema.
 * An unknown/non-public/unpublished form is a uniform 404 (no enumeration) -
 * never surfaced as a state here. */
export type PublicFormState = 'open' | 'closed' | 'full';

/** Public (pre-auth) fill view (slice 2). Tenant resolved from the subdomain
 * frontend-side and carried in the path; `honeypotField` is the bot-trap input
 * name injected at render (its value must post back empty). */
export interface PublicFormView {
  state: PublicFormState;
  formId: string;
  versionId: string;
  name: string;
  description: string | null;
  /** Only present when `state === 'open'`. */
  definition: FormDocument | null;
  paged: boolean;
  honeypotField: string;
  /** Friendly reason for closed/full (window vs cap), display-only. */
  message: string | null;
}

// ---- create/update payloads ----

export interface FormCreatePayload {
  name: string;
  description?: string;
  access?: FormAccess;
}

export interface FormUpdatePayload {
  name?: string;
  description?: string | null;
  access?: FormAccess;
  draftDefinition?: FormDocument;
  opensAt?: string | null;
  closesAt?: string | null;
  maxSubmissions?: number | null;
  submissionLimitPerUser?: number | null;
  pinnedColumns?: string[];
  displayMode?: 'paged' | 'single';
  allowRevisions?: boolean;
}
