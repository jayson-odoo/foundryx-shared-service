import type { ListQuery, ListResult } from '@/types/resource';
import type {
  CanvasDocument,
  Template,
  TemplateContext,
  TemplateDocument,
  TemplateInput,
  TemplateListItem,
} from '@/types/templates';
import { realTemplateEngineService } from './template-service.real';

export interface TemplatePreview {
  subject: string;
  html: string;
  text: string;
}

/**
 * Document (PDF) preview/render request — sprint-3/03 F2 D7. Renders the DRAFT
 * doc with the context's sample facts to `application/pdf` bytes. `id` is
 * omitted in create mode (draft never persisted); `download` flips the backend
 * to `Content-Disposition: attachment`.
 */
export interface DocumentPreviewInput {
  id?: string;
  doc: TemplateDocument;
  subject: string;
  context: string;
  download?: boolean;
}

/**
 * Canvas (badge) preview/render request — sprint-3/03 F2 slice 2. Renders the
 * DRAFT canvas doc with the context's sample facts. `id` is omitted in create
 * mode; `download` flips the backend to attachment disposition.
 */
export interface CanvasPreviewInput {
  id?: string;
  doc: CanvasDocument;
  context: string;
  download?: boolean;
}

export interface TemplateEngineService {
  listTemplates(query: ListQuery): Promise<ListResult<TemplateListItem>>;
  getTemplate(id: string): Promise<Template | null>;
  /** Record-nav: the row at `index` within the full result set of `query`. */
  getAt(query: ListQuery, index: number): Promise<{ template: TemplateListItem | null; total: number }>;
  listContexts(): Promise<TemplateContext[]>;
  /** Lightweight picker (BL-081) — templates of one context, for a SearchSelect. */
  listTemplateOptions(context: string): Promise<TemplateListItem[]>;
  createTemplate(input: TemplateInput): Promise<Template>;
  updateTemplate(id: string, input: TemplateInput): Promise<Template>;
  deleteTemplate(id: string): Promise<void>;
  duplicateTemplate(id: string): Promise<Template>;
  /** System templates only — drops the tenant fork (D6). */
  resetTemplate(id: string): Promise<Template>;
  /** Renders with the context's sample facts — same pipeline as production (D9). */
  preview(doc: TemplateDocument, contextKey: string, subject: string): Promise<TemplatePreview>;
  /**
   * Document surface: renders the draft to PDF bytes (WeasyPrint backend, D7).
   * `download` requests the attachment flavor. Returns the raw `application/pdf`
   * Blob — the caller builds an object URL for the embedded viewer / download.
   */
  previewDocumentPdf(input: DocumentPreviewInput): Promise<Blob>;
  /**
   * Document surface PREVIEW: the in-app preview HTML sheet (same compiler as
   * the PDF, no browser PDF-viewer chrome). Shown in a sandboxed iframe;
   * Download still uses `previewDocumentPdf`.
   */
  previewDocumentHtml(input: DocumentPreviewInput): Promise<string>;
  /**
   * Canvas (badge) surface: render the draft canvas doc to PDF bytes
   * (WeasyPrint, slice 2 D13). `download` requests the attachment flavor.
   */
  previewCanvasPdf(input: CanvasPreviewInput): Promise<Blob>;
  /**
   * Canvas (badge) PREVIEW: in-app preview HTML (stacked sheets, no browser
   * PDF-viewer chrome) — same compiler as the PDF; shown in a sandboxed iframe.
   */
  previewCanvasHtml(input: CanvasPreviewInput): Promise<string>;
  /** Renders with sample facts and emails the CURRENT user via the outbox. */
  testSend(id: string): Promise<{ toEmail: string }>;
  exportTemplates(query: ListQuery, columns: string[]): Promise<string>;
}

// Phase B: real api-client implementation (one-line boundary).
export const templateEngineService: TemplateEngineService = realTemplateEngineService;
