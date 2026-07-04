import { apiFetch, apiFetchBlob, apiFetchText } from '@/lib/api-client';
import { toCsv } from '@/lib/csv';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  AnyTemplateDoc,
  Template,
  TemplateContext,
  TemplateDocument,
  TemplateInput,
  TemplateListItem,
} from '@/types/templates';
import type {
  CanvasPreviewInput,
  DocumentPreviewInput,
  TemplateEngineService,
  TemplatePreview,
} from './template-service';

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
  return p;
}

function navParams(query: ListQuery, index: number): URLSearchParams {
  const p = listParams(query);
  p.delete('page');
  p.delete('page_size');
  p.set('index', String(index));
  return p;
}

interface TemplateDetailWire extends TemplateListItem {
  doc: AnyTemplateDoc;
}

export const realTemplateEngineService: TemplateEngineService = {
  listTemplates(query: ListQuery): Promise<ListResult<TemplateListItem>> {
    return apiFetch<ListResult<TemplateListItem>>(`/templates?${listParams(query).toString()}`);
  },

  getTemplate(id: string): Promise<Template | null> {
    return apiFetch<TemplateDetailWire>(`/templates/${id}`).catch(() => null);
  },

  getAt(query: ListQuery, index: number) {
    return apiFetch<{ template: TemplateListItem | null; total: number }>(
      `/templates/at?${navParams(query, index).toString()}`,
    );
  },

  listContexts(): Promise<TemplateContext[]> {
    return apiFetch<TemplateContext[]>('/templates/contexts');
  },

  listTemplateOptions(context: string): Promise<TemplateListItem[]> {
    const p = new URLSearchParams({ context, page: '0', page_size: '200' });
    return apiFetch<ListResult<TemplateListItem>>(`/templates?${p.toString()}`).then(
      (r) => r.data,
    );
  },

  createTemplate(input: TemplateInput): Promise<Template> {
    return apiFetch<TemplateDetailWire>('/templates', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  updateTemplate(id: string, input: TemplateInput): Promise<Template> {
    // context is immutable server-side; PATCH carries name/subject/doc.
    return apiFetch<TemplateDetailWire>(`/templates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name: input.name, subject: input.subject, doc: input.doc }),
    });
  },

  deleteTemplate(id: string): Promise<void> {
    return apiFetch(`/templates/${id}`, { method: 'DELETE' }) as Promise<void>;
  },

  duplicateTemplate(id: string): Promise<Template> {
    return apiFetch<TemplateDetailWire>(`/templates/${id}/duplicate`, { method: 'POST' });
  },

  resetTemplate(id: string): Promise<Template> {
    return apiFetch<TemplateDetailWire>(`/templates/${id}/reset`, { method: 'POST' });
  },

  preview(doc: TemplateDocument, contextKey: string, subject: string): Promise<TemplatePreview> {
    return apiFetch<TemplatePreview>('/templates/preview', {
      method: 'POST',
      body: JSON.stringify({ doc, context: contextKey, subject }),
    });
  },

  previewDocumentPdf(input: DocumentPreviewInput): Promise<Blob> {
    // ONE endpoint (backend `POST /templates/preview`): `format:'pdf'` in the
    // BODY selects the WeasyPrint emit step; `download` is a query flag for the
    // attachment flavor. The draft doc renders inline — `id` isn't needed for
    // the call (kept in the interface for the caller's convenience/logging).
    const params = new URLSearchParams();
    if (input.download) params.set('download', 'true');
    const qs = params.toString();
    return apiFetchBlob(`/templates/preview${qs ? `?${qs}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({
        doc: input.doc,
        context: input.context,
        subject: input.subject,
        format: 'pdf',
      }),
    });
  },

  previewDocumentHtml(input: DocumentPreviewInput): Promise<string> {
    // Same endpoint; `format:'docHtml'` returns the in-app preview HTML sheet
    // (text/html) instead of WeasyPrint bytes — no browser PDF-viewer chrome.
    return apiFetchText('/templates/preview', {
      method: 'POST',
      body: JSON.stringify({
        doc: input.doc,
        context: input.context,
        subject: input.subject,
        format: 'docHtml',
      }),
    });
  },

  previewCanvasPdf(input: CanvasPreviewInput): Promise<Blob> {
    // Same endpoint; `format:'canvasPdf'` selects the fixed-canvas WeasyPrint
    // emit step. Badge docs carry no subject.
    const params = new URLSearchParams();
    if (input.download) params.set('download', 'true');
    const qs = params.toString();
    return apiFetchBlob(`/templates/preview${qs ? `?${qs}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ doc: input.doc, context: input.context, subject: '', format: 'canvasPdf' }),
    });
  },

  previewCanvasHtml(input: CanvasPreviewInput): Promise<string> {
    // `format:'canvasHtml'` → in-app preview sheets (text/html).
    return apiFetchText('/templates/preview', {
      method: 'POST',
      body: JSON.stringify({ doc: input.doc, context: input.context, subject: '', format: 'canvasHtml' }),
    });
  },

  testSend(id: string): Promise<{ toEmail: string }> {
    return apiFetch<{ toEmail: string }>(`/templates/${id}/test-send`, { method: 'POST' });
  },

  async exportTemplates(query: ListQuery, columns: string[]): Promise<string> {
    // Client-side CSV over the filtered set (templates stay small; a backend
    // /export endpoint can replace this without touching callers).
    const full = await this.listTemplates({ ...query, page: 0, pageSize: 200 });
    const rows = full.data.map((t) =>
      columns.map((c) => String((t as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return toCsv(columns, rows);
  },
};
