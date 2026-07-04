/**
 * Field-type catalog (plan sprint-3/01 D7) — the single source for the
 * palette's category grouping, each type's lucide icon + label, and the
 * SearchSelect option lists the settings panel reuses. Mirrors the taxonomy
 * in `types/forms.ts` (parity with `lib/form-doc.ts FIELD_DEFAULT_LABELS`).
 */
import {
  AlignLeft,
  AtSign,
  Baseline,
  Calculator,
  CalendarClock,
  CalendarDays,
  CheckSquare,
  CircleDot,
  FileUp,
  Hash,
  Heading,
  Link as LinkIcon,
  ListChecks,
  MapPin,
  Minus,
  PenLine,
  Phone,
  Pilcrow,
  Repeat,
  Star,
  Table,
  Text as TextIcon,
  ToggleLeft,
  type LucideIcon,
} from 'lucide-react';
import { fieldDefaultLabel } from '@/lib/form-doc';
import type { FormFieldType, FormSubFieldType } from '@/types/forms';

export interface FieldTypeMeta {
  type: FormFieldType;
  label: string;
  icon: LucideIcon;
}

export interface PaletteCategory {
  /** Stable id used for the collapse-open state map. */
  id: string;
  label: string;
  types: FormFieldType[];
}

/** Icon per field type — used by the palette and the canvas type chip. */
export const FIELD_ICONS: Record<FormFieldType, LucideIcon> = {
  text: TextIcon,
  textarea: AlignLeft,
  email: AtSign,
  phone: Phone,
  url: LinkIcon,
  number: Hash,
  integer: Hash,
  select: ListChecks,
  multiselect: ListChecks,
  radio: CircleDot,
  checkboxes: CheckSquare,
  yesno: ToggleLeft,
  date: CalendarDays,
  datetime: CalendarClock,
  file: FileUp,
  signature: PenLine,
  rating: Star,
  address: MapPin,
  repeater: Repeat,
  table: Table,
  computed: Calculator,
  heading: Heading,
  paragraph: Pilcrow,
  divider: Minus,
};

/** Palette category grouping (D7). Order is the displayed order. */
export const PALETTE_CATEGORIES: PaletteCategory[] = [
  { id: 'text', label: 'Text', types: ['text', 'textarea', 'email', 'phone', 'url'] },
  { id: 'number', label: 'Number', types: ['number', 'integer'] },
  { id: 'choice', label: 'Choice', types: ['select', 'multiselect', 'radio', 'checkboxes', 'yesno'] },
  { id: 'date', label: 'Date', types: ['date', 'datetime'] },
  { id: 'upload', label: 'Upload', types: ['file', 'signature'] },
  { id: 'scoring', label: 'Scoring', types: ['rating'] },
  { id: 'composite', label: 'Composite', types: ['address', 'repeater', 'table'] },
  { id: 'computed', label: 'Computed', types: ['computed'] },
  { id: 'display', label: 'Display', types: ['heading', 'paragraph', 'divider'] },
];

export function fieldMeta(type: FormFieldType): FieldTypeMeta {
  return { type, label: fieldDefaultLabel(type), icon: FIELD_ICONS[type] ?? Baseline };
}

// ---- sub-field (repeater) types ----

export const SUB_FIELD_TYPES: FormSubFieldType[] = [
  'text',
  'textarea',
  'email',
  'phone',
  'url',
  'number',
  'select',
  'radio',
  'yesno',
  'date',
  'rating',
];

// ---- common file mime whitelist (file field) ----

export const COMMON_MIMES: { value: string; label: string }[] = [
  { value: 'application/pdf', label: 'PDF' },
  { value: 'image/png', label: 'PNG image' },
  { value: 'image/jpeg', label: 'JPEG image' },
  { value: 'image/webp', label: 'WebP image' },
  {
    value: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    label: 'Word (.docx)',
  },
  {
    value: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    label: 'Excel (.xlsx)',
  },
  {
    value: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    label: 'PowerPoint (.pptx)',
  },
];
