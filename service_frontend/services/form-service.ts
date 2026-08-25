/**
 * Form engine service boundary (plan sprint-3/01). Phase A binds the mock;
 * Phase B swaps to the real api-client implementation at this one line
 * (house methodology - UI → hook → service → api-client).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  FormAnswers,
  FormCreatePayload,
  FormDetail,
  FormDocument,
  FormFieldErrors,
  FormFillView,
  FormRow,
  FormSubmissionRow,
  FormUpdatePayload,
  FormVersionRow,
} from '@/types/forms';
import { realFormService } from './form-service.real';

/** Publish refused - the validate gate's problem list (422 contract, D9). */
export class FormPublishError extends Error {
  problems: string[];

  constructor(problems: string[]) {
    super(problems.join(' '));
    this.name = 'FormPublishError';
    this.problems = problems;
  }
}

/** Submit refused - per-field error map (422 contract, D14). */
export class FormSubmitError extends Error {
  fieldErrors: FormFieldErrors;

  constructor(fieldErrors: FormFieldErrors, message = 'Some answers need attention.') {
    super(message);
    this.name = 'FormSubmitError';
    this.fieldErrors = fieldErrors;
  }
}

/** The scoped status graph backing the Submissions tab's transition buttons
 * (Phase B: the scope-filtered graph endpoint). */
export interface FormSubmissionGraph {
  statuses: {
    id: string;
    key: string;
    label: string;
    color: string;
    isInitial: boolean;
    isActive: boolean;
    isTerminal: boolean;
  }[];
  transitions: { id: string; label: string; fromStatusId: string; toStatusId: string }[];
}

export interface FormService {
  list(query: ListQuery): Promise<ListResult<FormRow>>;
  getAt(query: ListQuery, index: number): Promise<{ form: FormRow | null; total: number }>;
  get(id: string): Promise<FormDetail | null>;
  create(payload: FormCreatePayload): Promise<FormDetail>;
  update(id: string, payload: FormUpdatePayload): Promise<FormDetail>;
  /** Validate gate + snapshot (D9). Throws `FormPublishError`. */
  publish(id: string): Promise<FormDetail>;
  unpublish(id: string): Promise<FormDetail>;
  archive(id: string): Promise<FormRow>;
  restore(id: string): Promise<FormRow>;
  /** Hard delete - drops versions, submissions and the scoped status graph. */
  remove(id: string): Promise<void>;
  export(query: ListQuery, columns: string[]): Promise<string>;

  versions(formId: string, page: number, pageSize: number): Promise<ListResult<FormVersionRow>>;
  /** The immutable definition of one published version - submissions re-render
   * against their PINNED version forever (D9). */
  versionDefinition(formId: string, versionId: string): Promise<FormDocument | null>;
  /** Author preview - renders the DRAFT (D9). */
  preview(formId: string): Promise<FormFillView>;
  /** Fill surface - the PUBLISHED version only (D9). Null = not published. */
  fill(formId: string): Promise<FormFillView | null>;
  /** Internal submit (any authed user, D19). Throws `FormSubmitError` on 422. */
  submit(formId: string, answers: FormAnswers): Promise<FormSubmissionRow>;

  submissions(formId: string, query: ListQuery): Promise<ListResult<FormSubmissionRow>>;
  getSubmission(id: string): Promise<FormSubmissionRow | null>;
  submissionGraph(formId: string): Promise<FormSubmissionGraph>;
  /** Fire one edge of the form's scoped machine (graph-driven buttons, D15). */
  transitionSubmission(id: string, transitionId: string): Promise<FormSubmissionRow>;
  exportSubmissions(formId: string, query: ListQuery, columns: string[]): Promise<string>;

  /** Clone a frozen current submission into a NEW Draft revision (plan
   * sprint-4/04 R2). Returns the Draft row; the author then edits + resubmits.
   * Rejects (409) if revisions are off / not current / not frozen / no version. */
  revise(submissionId: string): Promise<FormSubmissionRow>;
  /** The full revision chain for a group, newest first (R3 history). Each row
   * pins its OWN version for faithful re-render. */
  submissionRevisions(formId: string, groupId: string): Promise<FormSubmissionRow[]>;
  /** Save edited answers into a Draft revision + fire its Submit edge (R3 -
   * rides the existing submit/transition flow). Throws `FormSubmitError` on 422. */
  resubmitRevision(submissionId: string, answers: FormAnswers): Promise<FormSubmissionRow>;
}

// Phase B: swap to the real api-client implementation (one-line boundary).
export const formService: FormService = realFormService;
