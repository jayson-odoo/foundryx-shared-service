import type { RuleGroup } from '@/types/rules';

/**
 * Template Engine block document - plan sprint-2/07 D2/D3.
 *
 * THE FOREVER-CONTRACT: this JSON shape is editor-agnostic and outlives any
 * editor implementation (research: Mailchimp's classic↔new migration wall).
 * Breaking shape changes bump TEMPLATE_SCHEMA_VERSION (migrate-on-read).
 */
export const TEMPLATE_SCHEMA_VERSION = 1;

/** Section column layouts - fixed ratios only (email clients; D3). */
export type SectionLayout = '100' | '50/50' | '33/33/33' | '67/33';

export const SECTION_LAYOUT_COLUMNS: Record<SectionLayout, number[]> = {
  '100': [100],
  '50/50': [50, 50],
  '33/33/33': [33.33, 33.33, 33.34],
  '67/33': [67, 33],
};

export interface BlockPadding {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export type TextAlign = 'left' | 'center' | 'right';

// ---------------------------------------------------------------------------
// Blocks (discriminated union on `type`)
// ---------------------------------------------------------------------------

interface BaseBlock {
  id: string;
  /** Rule-engine visibility tree (plan 02 schema); null = always rendered. */
  conditionsJson?: RuleGroup | null;
}

export interface HeadingBlock extends BaseBlock {
  type: 'heading';
  /** Merge-enabled ({{dotted.path}} tokens allowed). */
  text: string;
  level: 1 | 2 | 3;
  align: TextAlign;
}

export interface TextBlock extends BaseBlock {
  type: 'text';
  /**
   * Rich-lite HTML (b/i/u/a/ul/ol/li only - sanitized server-side at save);
   * merge-enabled.
   */
  html: string;
  align: TextAlign;
}

export interface ImageBlock extends BaseBlock {
  type: 'image';
  /** StorageService key; resolved to a URL at render. Empty = placeholder. */
  storageKey: string | null;
  /** Direct URL alternative (mock phase + external images). */
  src: string | null;
  alt: string;
  /** Pixel width; null = natural/full column width. */
  width: number | null;
  align: TextAlign;
  /** Optional wrapping link (merge-enabled). */
  href: string | null;
}

export interface ButtonBlock extends BaseBlock {
  type: 'button';
  /** Merge-enabled. */
  label: string;
  /** Merge-enabled (e.g. {{resetLink}}); URL-validated at render. */
  href: string;
  align: TextAlign;
  /** null = brand primary at render time. */
  backgroundColor: string | null;
  textColor: string | null;
  borderRadius: number;
}

export interface DividerBlock extends BaseBlock {
  type: 'divider';
  color: string;
  thickness: number;
}

export interface SpacerBlock extends BaseBlock {
  type: 'spacer';
  height: number;
}

export type SocialPlatform =
  | 'facebook'
  | 'instagram'
  | 'x'
  | 'linkedin'
  | 'youtube'
  | 'tiktok'
  | 'website';

export interface SocialLinksBlock extends BaseBlock {
  type: 'socialLinks';
  /**
   * null = render every URL the tenant set in branding (D4 live-follow);
   * a list = explicit subset/override [{platform, href}].
   */
  links: { platform: SocialPlatform; href: string }[] | null;
  align: TextAlign;
  iconSize: number;
}

export interface BrandHeaderBlock extends BaseBlock {
  type: 'brandHeader';
  /** Overrides for branding-resolved values; null members = live brand value. */
  overrides: {
    logoSrc?: string | null;
    backgroundColor?: string | null;
  } | null;
}

export interface BrandFooterBlock extends BaseBlock {
  type: 'brandFooter';
  overrides: {
    footerText?: string | null;
    backgroundColor?: string | null;
    showSocials?: boolean;
  } | null;
}

export interface CustomHtmlBlock extends BaseBlock {
  type: 'customHtml';
  /** Sanitized server-side at save (nh3); rendered via mj-raw. */
  html: string;
}

/** QR block (flowing email/document surface) - a centred QR image, fixed px. */
export interface QrBlock extends BaseBlock {
  type: 'qr';
  /** Merge-enabled payload (e.g. {{ticketLink}}). */
  data: string;
  ecLevel: QrErrorCorrection;
  /** Pixel size. */
  size: number;
  align: TextAlign;
}

// --- F2 document-surface blocks (table / repeater) -------------------------
// Iterate a LIST fact. Repetition is STRUCTURAL (expand-before-compile); the
// merge renderer stays substitution-only. Body refs use the `row.<key>` scope.

export interface TableColumn {
  /** Binds row.<key>. */
  key: string;
  header: string;
  align: TextAlign;
  /** Column width as a percentage; null = auto. */
  width: number | null;
}

export interface TableFooterCell {
  /** Scalar merge tokens only (domain-owned totals, e.g. {{total}}). */
  text: string;
  align: TextAlign;
  span: number;
}

export interface TableFooterRow {
  cells: TableFooterCell[];
}

export interface TableBlock extends BaseBlock {
  type: 'table';
  /** List-fact key. */
  source: string;
  columns: TableColumn[];
  footer: TableFooterRow[] | null;
}

/** Leaf blocks legal inside a repeater body - single level, no nesting. */
export type RepeaterBodyBlock =
  | HeadingBlock
  | TextBlock
  | ImageBlock
  | ButtonBlock
  | DividerBlock
  | SpacerBlock
  | QrBlock;

export interface RepeaterBlock extends BaseBlock {
  type: 'repeater';
  /** List-fact key. */
  source: string;
  body: RepeaterBodyBlock[];
}

export type TemplateBlock =
  | HeadingBlock
  | TextBlock
  | ImageBlock
  | ButtonBlock
  | DividerBlock
  | SpacerBlock
  | SocialLinksBlock
  | BrandHeaderBlock
  | BrandFooterBlock
  | CustomHtmlBlock
  | QrBlock
  | TableBlock
  | RepeaterBlock;

export type TemplateBlockType = TemplateBlock['type'];

// ---------------------------------------------------------------------------
// Sections & document
// ---------------------------------------------------------------------------

export interface TemplateColumn {
  id: string;
  blocks: TemplateBlock[];
}

export interface TemplateSection {
  id: string;
  layout: SectionLayout;
  background: string | null;
  padding: BlockPadding;
  conditionsJson?: RuleGroup | null;
  /** Column count always matches SECTION_LAYOUT_COLUMNS[layout].length. */
  columns: TemplateColumn[];
}

export interface PageMargins {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** Document-surface only (PDF render); email docs omit it. Units = mm. */
export interface PageSetup {
  size: 'A4' | 'Letter';
  orientation: 'portrait' | 'landscape';
  margins: PageMargins;
}

export interface TemplateDocument {
  schemaVersion: typeof TEMPLATE_SCHEMA_VERSION;
  pageSetup?: PageSetup | null;
  sections: TemplateSection[];
}

// ---------------------------------------------------------------------------
// F2 slice 2 - fixed-canvas document (badge / ticket / certificate)
// ---------------------------------------------------------------------------
// A SECOND doc shape, polymorphic by template `type`: block-doc when
// email/document, canvas-doc when badge. Absolute-positioned elements over a
// fixed physical page (plan sprint-3/03 D14). Coordinates are stored in mm
// (print-authoritative); `canvas.unit` is the editor's DISPLAY/input unit only
// - render is always mm. `z` = array order (no explicit field). Context lives
// on the Template row (`context`), as with every other doc shape.

/** Editor display/input unit. Stored geometry is always mm. */
export type CanvasUnit = 'mm' | 'in' | 'px';

export type CanvasElementType =
  | 'text'
  | 'image'
  | 'shape'
  | 'qr'
  | 'divider'
  | 'socialLinks'
  | 'customHtml'
  | 'brandHeader'
  | 'brandFooter';

interface BaseCanvasElement {
  id: string;
  type: CanvasElementType;
  /** mm, top-left origin. */
  x: number;
  y: number;
  w: number;
  h: number;
  /** Clockwise degrees. */
  rotation: number;
  /** Rule-engine visibility (plan 02); null = always rendered. */
  conditionsJson?: RuleGroup | null;
}

export interface CanvasTextElement extends BaseCanvasElement {
  type: 'text';
  /** Merge-enabled ({{dotted.path}}), mixed static + dynamic. */
  content: string;
  /** A bundled family name (see CANVAS_FONTS / backend fonts.py FONT_NAMES). */
  fontFamily: string;
  /** Points. */
  fontSize: number;
  weight: 400 | 600 | 700;
  align: TextAlign;
  color: string;
  lineHeight: number;
}

export interface CanvasImageElement extends BaseCanvasElement {
  type: 'image';
  /** StorageService key; resolved to a URL at render. */
  storageKey: string | null;
  /** Direct URL OR a {{fact}} token (merge-enabled). */
  src: string | null;
  fit: 'contain' | 'cover';
}

export type CanvasShapeKind = 'rect' | 'ellipse' | 'line';

export interface CanvasShapeElement extends BaseCanvasElement {
  type: 'shape';
  kind: CanvasShapeKind;
  fill: string | null;
  stroke: string | null;
  strokeWidth: number;
  /** rect corner radius (mm); ignored for ellipse/line. */
  radius: number;
}

export type QrErrorCorrection = 'L' | 'M' | 'Q' | 'H';

export interface CanvasQrElement extends BaseCanvasElement {
  type: 'qr';
  /** Merge-enabled - the encoded payload (e.g. {{ticketCode}}). */
  data: string;
  ecLevel: QrErrorCorrection;
}

/** Cross-surface parity - flowing-block elements positioned on the fixed card. */
export interface CanvasDividerElement extends BaseCanvasElement {
  type: 'divider';
  color: string;
  /** mm. */
  thickness: number;
}

export interface CanvasSocialElement extends BaseCanvasElement {
  type: 'socialLinks';
  /** null = render the tenant's branding socials at render time. */
  links: { platform: SocialPlatform; href: string }[] | null;
  align: TextAlign;
  iconSize: number;
}

export interface CanvasHtmlElement extends BaseCanvasElement {
  type: 'customHtml';
  /** Sanitized server-side at save (nh3). */
  html: string;
}

/** Auto-logo bar - branding-driven, live-follows a rebrand. */
export interface CanvasBrandHeaderElement extends BaseCanvasElement {
  type: 'brandHeader';
  overrides: { logoSrc?: string | null; backgroundColor?: string | null } | null;
}

export interface CanvasBrandFooterElement extends BaseCanvasElement {
  type: 'brandFooter';
  overrides: {
    footerText?: string | null;
    backgroundColor?: string | null;
    showSocials?: boolean;
  } | null;
}

export type CanvasElement =
  | CanvasTextElement
  | CanvasImageElement
  | CanvasShapeElement
  | CanvasQrElement
  | CanvasDividerElement
  | CanvasSocialElement
  | CanvasHtmlElement
  | CanvasBrandHeaderElement
  | CanvasBrandFooterElement;

export interface CanvasSide {
  /** 'front' | 'back' (or a custom label); N sides → N pages. */
  name: string;
  elements: CanvasElement[];
}

export interface CanvasSize {
  /** mm. */
  width: number;
  height: number;
  /** Editor display/input unit (geometry is always stored in mm). */
  unit: CanvasUnit;
  orientation: 'portrait' | 'landscape';
  /** Print trim bleed in mm (typically 3). */
  bleed: number;
}

/** Polymorphic doc for `type==='badge'` (forever-contract - D14). */
export interface CanvasDocument {
  schemaVersion: typeof TEMPLATE_SCHEMA_VERSION;
  canvas: CanvasSize;
  /** Front + optional back (single-sided ticket/cert = one side). */
  sides: CanvasSide[];
}

// ---------------------------------------------------------------------------
// Template entity (two-tier - D6)
// ---------------------------------------------------------------------------

export type TemplateType = 'email' | 'document' | 'badge';

/** Block-doc (email/document) OR canvas-doc (badge), polymorphic by `type`. */
export type AnyTemplateDoc = TemplateDocument | CanvasDocument;

/** Narrow {@link AnyTemplateDoc} to the canvas shape. */
export function isCanvasDoc(doc: AnyTemplateDoc): doc is CanvasDocument {
  return 'canvas' in doc && 'sides' in doc;
}

/** 'default' = platform tier row; 'customized' = tenant fork / tenant-owned. */
export type TemplateTier = 'default' | 'customized';

export interface TemplateListItem {
  id: string;
  key: string;
  name: string;
  type: TemplateType;
  context: string;
  contextLabel: string;
  tier: TemplateTier;
  isSystem: boolean;
  subject: string;
  updatedAt: string;
  createdAt: string;
}

export interface Template extends TemplateListItem {
  /** Block-doc (email/document) or canvas-doc (badge) - narrow by `type`. */
  doc: AnyTemplateDoc;
}

export interface TemplateInput {
  name: string;
  subject: string;
  context: string;
  doc: AnyTemplateDoc;
  /** Surface type; omitted = 'email' (backend default). Set on create only. */
  type?: TemplateType;
}

// ---------------------------------------------------------------------------
// Template contexts (code-side registry - D11)
// ---------------------------------------------------------------------------

export interface TemplateContextFact {
  key: string;
  label: string;
  /** Sample value for preview/test-send/editor chips. */
  sample: string;
}

/** A list fact - bound by a table/repeater `source`; rows expose `row.<key>`. */
export interface TemplateListFact {
  key: string;
  label: string;
  /** Row sub-fields (the `row.*` vocabulary for the iterator body). */
  itemFacts: TemplateContextFact[];
}

export interface TemplateContext {
  key: string;
  label: string;
  /** Rule-engine fact sources available for block visibility conditions. */
  factSources: string[];
  /** Merge-field vocabulary (incl. samples). */
  facts: TemplateContextFact[];
  /** List facts bindable by table/repeater blocks (document surface). */
  listFacts?: TemplateListFact[];
  /** Fact keys that MUST appear in the doc/subject (save-time 422 - D7). */
  requiredFacts: string[];
}

// ---------------------------------------------------------------------------
// Email outbox (Email log - D14)
// ---------------------------------------------------------------------------

export type EmailOutboxStatus =
  | 'PENDING'
  | 'SENDING'
  | 'SENT'
  | 'FAILED'
  | 'CANCELLED';

export interface EmailLogListItem {
  id: string;
  toEmail: string;
  subject: string;
  templateKey: string;
  status: EmailOutboxStatus;
  attempts: number;
  usedFallback: boolean;
  createdAt: string;
  sentAt: string | null;
  nextAttemptAt: string | null;
}

export interface EmailLogDetail extends EmailLogListItem {
  htmlBody: string;
  textBody: string;
  lastError: string | null;
  connectionId: string | null;
}
