/**
 * Real form service (Phase B) - talks to FastAPI via the shared api-client.
 * Endpoints follow plan sprint-3/01 §API. Error contracts: publish 422 carries
 * `{problems: string[]}` → FormPublishError; submit 422 carries
 * `{fieldErrors: {key: message}}` → FormSubmitError.
 */
import { ApiError, apiFetch } from '@/lib/api-client';
import { toCsv } from '@/lib/csv';
import { buildSubmitBody } from '@/lib/form-submit-body';
import type { ListQuery } from '@/types/resource';
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
} from '@/types/forms';
import {
  FormPublishError,
  FormSubmitError,
  type FormService,
  type FormSubmissionGraph,
} from './form-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  if (query.statusView) p.set('status_view', query.statusView);
  if (query.segment) p.set('segment', query.segment);
  return p;
}

/** 422 details ride ApiError.detail (api-client) - translate the engine's
 * structured shapes into the service error classes the UI consumes. */
function detailOf(error: unknown): unknown {
  return error instanceof ApiError ? error.detail : undefined;
}

function cellValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export const realFormService: FormService = {
  list(query) {
    return apiFetch(`/forms?${listParams(query).toString()}`);
  },

  getAt(query, index) {
    const p = listParams(query);
    p.delete('page');
    p.delete('page_size');
    p.set('index', String(index));
    return apiFetch(`/forms/at?${p.toString()}`);
  },

  get(id) {
    return apiFetch<FormDetail>(`/forms/${id}`).catch(() => null);
  },

  create(payload: FormCreatePayload) {
    return apiFetch<FormDetail>('/forms', { method: 'POST', body: JSON.stringify(payload) });
  },

  update(id, payload: FormUpdatePayload) {
    return apiFetch<FormDetail>(`/forms/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  async publish(id) {
    try {
      return await apiFetch<FormDetail>(`/forms/${id}/publish`, { method: 'POST' });
    } catch (error) {
      const detail = detailOf(error) as { problems?: string[] } | undefined;
      if (detail?.problems) throw new FormPublishError(detail.problems);
      throw error;
    }
  },

  unpublish(id) {
    return apiFetch<FormDetail>(`/forms/${id}/unpublish`, { method: 'POST' });
  },

  archive(id) {
    return apiFetch<FormRow>(`/forms/${id}/archive`, { method: 'POST' });
  },

  restore(id) {
    return apiFetch<FormRow>(`/forms/${id}/restore`, { method: 'POST' });
  },

  async remove(id) {
    await apiFetch<void>(`/forms/${id}`, { method: 'DELETE' });
  },

  async export(query, columns) {
    const full = await this.list({ ...query, page: 0, pageSize: 10_000 });
    const rows = full.data.map((r) =>
      columns.map((c) => cellValue((r as unknown as Record<string, unknown>)[c])),
    );
    return toCsv(columns, rows);
  },

  versions(formId, page, pageSize) {
    return apiFetch(`/forms/${formId}/versions?page=${page}&page_size=${pageSize}`);
  },

  versionDefinition(formId, versionId) {
    return apiFetch<{ id: string; versionNumber: number; definition: FormDocument }>(
      `/forms/${formId}/versions/${versionId}`,
    )
      .then((r) => r.definition)
      .catch(() => null);
  },

  preview(formId) {
    return apiFetch<FormFillView>(`/forms/${formId}/preview`, { method: 'POST' });
  },

  fill(formId) {
    return apiFetch<FormFillView>(`/forms/${formId}/fill`).catch(() => null);
  },

  async submit(formId, answers: FormAnswers) {
    try {
      // Multipart when file fields carry staged uploads; JSON otherwise (D12).
      const { body } = buildSubmitBody(answers);
      return await apiFetch<FormSubmissionRow>(`/forms/${formId}/submissions`, {
        method: 'POST',
        body,
      });
    } catch (error) {
      const detail = detailOf(error) as { fieldErrors?: FormFieldErrors } | undefined;
      if (detail?.fieldErrors) throw new FormSubmitError(detail.fieldErrors);
      throw error;
    }
  },

  submissions(formId, query) {
    return apiFetch(`/forms/${formId}/submissions?${listParams(query).toString()}`);
  },

  getSubmission(id) {
    return apiFetch<FormSubmissionRow>(`/submissions/${id}`).catch(() => null);
  },

  submissionGraph(formId) {
    return apiFetch<FormSubmissionGraph>(`/forms/${formId}/graph`);
  },

  transitionSubmission(id, transitionId) {
    return apiFetch<FormSubmissionRow>(`/submissions/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ transitionId }),
    });
  },

  revise(submissionId) {
    return apiFetch<FormSubmissionRow>(`/submissions/${submissionId}/revise`, { method: 'POST' });
  },

  submissionRevisions(formId, groupId) {
    return apiFetch<{ data: FormSubmissionRow[] }>(
      `/forms/${formId}/submissions?group=${encodeURIComponent(groupId)}&page=0&page_size=200`,
    ).then((r) => r.data);
  },

  async resubmitRevision(submissionId, answers: FormAnswers) {
    try {
      const { body } = buildSubmitBody(answers);
      return await apiFetch<FormSubmissionRow>(`/submissions/${submissionId}/resubmit`, {
        method: 'POST',
        body,
      });
    } catch (error) {
      const detail = detailOf(error) as { fieldErrors?: FormFieldErrors } | undefined;
      if (detail?.fieldErrors) throw new FormSubmitError(detail.fieldErrors);
      throw error;
    }
  },

  async exportSubmissions(formId, query, columns) {
    const result = await this.submissions(formId, { ...query, page: 0, pageSize: 10_000 });
    const rows = result.data.map((s) =>
      columns.map((c) => {
        if (c.startsWith('answers.')) return cellValue(s.answers[c.slice('answers.'.length)]);
        if (c === 'respondent') return s.userName ?? 'Anonymous';
        return cellValue((s as unknown as Record<string, unknown>)[c]);
      }),
    );
    return toCsv(columns, rows);
  },
};
