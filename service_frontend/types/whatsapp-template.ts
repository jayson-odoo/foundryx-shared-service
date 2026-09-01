/**
 * WhatsApp template domain types (plan 07) - mirror of the backend
 * `modules/omnichannel/template_schemas.py` + schemas. The friendly
 * `WaTemplateDoc` is what the builder edits; the canonical store is the Meta
 * component array. Transform lives in `lib/whatsapp-template.ts`.
 */

export type TemplateCategory = 'MARKETING' | 'UTILITY';
export type HeaderFormat = 'TEXT' | 'IMAGE' | 'VIDEO' | 'DOCUMENT';
export type MediaHeaderFormat = 'IMAGE' | 'VIDEO' | 'DOCUMENT';
export type ButtonType = 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER' | 'COPY_CODE';
export type TemplateStatus =
  | 'LOCAL_DRAFT'
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'PAUSED'
  | 'DISABLED';

export interface WaTextHeader {
  format: 'TEXT';
  text: string;
  example?: string | null;
}
export interface WaMediaHeader {
  format: MediaHeaderFormat;
  sampleKey?: string | null;
}
export type WaHeader = WaTextHeader | WaMediaHeader;

export interface WaBody {
  text: string;
  examples: string[];
}
export interface WaFooter {
  text: string;
}
export interface WaButton {
  type: ButtonType;
  text?: string | null;
  url?: string | null;
  example?: string | null;
  phoneNumber?: string | null;
}

export interface WaTemplateDoc {
  name: string;
  category: TemplateCategory;
  language: string;
  header?: WaHeader | null;
  body: WaBody;
  footer?: WaFooter | null;
  buttons?: WaButton[] | null;
}

/** A row in the Templates tab list (mirrors backend TemplateManageItem). */
export interface TemplateManageItem {
  id: string;
  channelId: string;
  name: string;
  language: string | null;
  category: string | null;
  status: TemplateStatus;
  quality: string | null; // GREEN | YELLOW | RED
  rejectedReason: string | null;
  bodyPreview: string;
  variableCount: number;
  metaTemplateId: string | null;
  lastSyncedAt: string | null;
  createdAt: string;
}

/** Single-template detail: list item + the builder doc + raw Meta components. */
export interface TemplateDetail extends TemplateManageItem {
  doc: WaTemplateDoc;
  components: Record<string, unknown>[];
}
