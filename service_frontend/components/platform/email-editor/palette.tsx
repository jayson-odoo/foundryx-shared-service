'use client';

import { useDraggable } from '@dnd-kit/core';
import {
  Code,
  Heading1,
  Image as ImageIcon,
  Minus,
  MousePointerClick,
  PanelTop,
  PanelBottom,
  QrCode,
  Repeat,
  Share2,
  StretchVertical,
  Table as TableIcon,
  Type,
  type LucideIcon,
} from 'lucide-react';
import {
  CollapsiblePalette,
  type PaletteCategory,
} from '@/components/platform/palette/collapsible-palette';
import type { TemplateBlockType } from '@/types/templates';
import type { EditorSurface } from './email-editor';

export interface PaletteEntry {
  type: TemplateBlockType;
  label: string;
  icon: LucideIcon;
}

const ENTRIES: Record<TemplateBlockType, PaletteEntry> = {
  heading: { type: 'heading', label: 'Heading', icon: Heading1 },
  text: { type: 'text', label: 'Text', icon: Type },
  image: { type: 'image', label: 'Image', icon: ImageIcon },
  button: { type: 'button', label: 'Button', icon: MousePointerClick },
  divider: { type: 'divider', label: 'Divider', icon: Minus },
  spacer: { type: 'spacer', label: 'Spacer', icon: StretchVertical },
  socialLinks: { type: 'socialLinks', label: 'Social links', icon: Share2 },
  brandHeader: { type: 'brandHeader', label: 'Brand header', icon: PanelTop },
  brandFooter: { type: 'brandFooter', label: 'Brand footer', icon: PanelBottom },
  customHtml: { type: 'customHtml', label: 'Custom HTML', icon: Code },
  qr: { type: 'qr', label: 'QR code', icon: QrCode },
  table: { type: 'table', label: 'Table', icon: TableIcon },
  repeater: { type: 'repeater', label: 'Repeater', icon: Repeat },
};

const EMAIL_BLOCKS: TemplateBlockType[] = [
  'heading',
  'text',
  'image',
  'button',
  'divider',
  'spacer',
  'socialLinks',
  'qr',
  'brandHeader',
  'brandFooter',
  'customHtml',
];

// Document surface (F2): + table/repeater + qr, − socialLinks (paper, not email).
const DOCUMENT_BLOCKS: TemplateBlockType[] = [
  'heading',
  'text',
  'image',
  'button',
  'divider',
  'spacer',
  'qr',
  'table',
  'repeater',
  'brandHeader',
  'brandFooter',
];

/** The default (email) palette - kept exported for the existing email tests. */
export const PALETTE: PaletteEntry[] = EMAIL_BLOCKS.map((t) => ENTRIES[t]);

/** Palette entries for a given editor surface. */
export function paletteFor(surface: EditorSurface): PaletteEntry[] {
  return (surface === 'document' ? DOCUMENT_BLOCKS : EMAIL_BLOCKS).map((t) => ENTRIES[t]);
}

/** Display label for any block type (drag overlay) - across all surfaces. */
export function labelForBlockType(type: TemplateBlockType): string {
  return ENTRIES[type]?.label ?? type;
}

// Grouped categories (house collapsible/searchable pattern). Filtered per
// surface to the blocks it allows.
const CATEGORY_TEMPLATE: PaletteCategory<TemplateBlockType>[] = [
  { id: 'content', label: 'Content', types: ['heading', 'text', 'image', 'button', 'qr'] },
  { id: 'layout', label: 'Layout', types: ['divider', 'spacer'] },
  { id: 'branding', label: 'Branding', types: ['brandHeader', 'brandFooter', 'socialLinks'] },
  { id: 'data', label: 'Data', types: ['table', 'repeater'] },
  { id: 'advanced', label: 'Advanced', types: ['customHtml'] },
];

function categoriesFor(surface: EditorSurface): PaletteCategory<TemplateBlockType>[] {
  const allowed = new Set(surface === 'document' ? DOCUMENT_BLOCKS : EMAIL_BLOCKS);
  return CATEGORY_TEMPLATE.map((c) => ({ ...c, types: c.types.filter((t) => allowed.has(t)) })).filter(
    (c) => c.types.length > 0,
  );
}

function PaletteItem({ type, disabled }: { type: TemplateBlockType; disabled: boolean }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette-${type}`,
    data: { source: 'palette', blockType: type },
    disabled,
  });
  const Icon = ENTRIES[type].icon;
  return (
    <button
      ref={setNodeRef}
      type="button"
      data-testid={`palette-${type}`}
      className={`flex w-full items-center gap-2 rounded-md border border-input bg-background px-2.5 py-1.5 text-left text-xs text-foreground transition-colors ${
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-grab hover:border-primary hover:text-primary'
      } ${isDragging ? 'opacity-40' : ''}`}
      {...listeners}
      {...attributes}
    >
      <Icon className="size-4 shrink-0" />
      <span className="truncate">{ENTRIES[type].label}</span>
    </button>
  );
}

/** Grouped / collapsible / searchable block palette (house pattern). */
export function Palette({
  disabled,
  surface = 'email',
}: {
  disabled: boolean;
  surface?: EditorSurface;
}) {
  return (
    <CollapsiblePalette
      testId="email-block-palette"
      searchPlaceholder="Search blocks"
      categories={categoriesFor(surface)}
      defaultOpenIds={['content']}
      labelFor={labelForBlockType}
      renderItem={(type) => <PaletteItem type={type} disabled={disabled} />}
    />
  );
}
