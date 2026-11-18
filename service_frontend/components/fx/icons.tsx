/**
 * One icon per meaning (playbook 0.71.0 "Shape, icons and text" and the Other
 * Actions table). Line icons on a 24px grid, stroke 2, round ends, in
 * `currentColor`; 16px in text and dense rows, 18px in buttons, 24px in menus
 * and empty states. Pages name an icon by meaning (`FxIconName`), never pick a
 * glyph of their own, so the same action never gets two icons.
 */
import type { SVGProps } from 'react';
import {
  ArrowLeftRight,
  Bell,
  BellRing,
  ChevronLeft,
  ChevronRight,
  Copy,
  Ellipsis,
  Filter,
  LayoutGrid,
  Mail,
  Menu,
  MessageCircleMore,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Settings2,
  Share2,
  Tag,
  Trash2,
  Undo2,
  UserPlus,
  X,
  type LucideIcon,
} from 'lucide-react';

export type FxIconSize = 16 | 18 | 24;

/** File types the playbook draws as a page with a type tag. */
export type FxFileType = 'PDF' | 'CSV' | 'SOA' | 'BANK';

/** Meanings with a fixed glyph. File actions use `FxFileIcon` instead. */
export const FX_ICONS = {
  add: Plus,
  assign: UserPlus,
  copy: Copy,
  delete: X,
  discard: Undo2,
  edit: Pencil,
  email: Mail,
  filter: Filter,
  more: Ellipsis,
  move: ArrowLeftRight,
  refresh: RefreshCw,
  reminder: BellRing,
  search: Search,
  send: Send,
  settings: Settings,
  share: Share2,
  tag: Tag,
  trash: Trash2,
  close: X,
  // Shell (slice F5): the top bar and the side panel.
  jobs: Settings2,
  notifications: Bell,
  chat: MessageCircleMore,
  apps: LayoutGrid,
  menu: Menu,
  pin: Pin,
  unpin: PinOff,
  previous: ChevronLeft,
  next: ChevronRight,
} satisfies Record<string, LucideIcon>;

export type FxIconName = keyof typeof FX_ICONS;

/** File action names: `pdf`, `pdf-down`, `csv-down`, `soa`, `bank-up`, ... */
export type FxFileIconName = `${Lowercase<FxFileType>}${'' | '-down' | '-up'}`;

export type FxAnyIconName = FxIconName | FxFileIconName;

interface FxIconProps {
  name: FxAnyIconName;
  size?: FxIconSize;
  className?: string;
}

/** Draws an icon by meaning. */
export function FxIcon({ name, size = 18, className }: FxIconProps) {
  if (name in FX_ICONS) {
    const Glyph = FX_ICONS[name as FxIconName];
    return (
      <Glyph
        aria-hidden="true"
        width={size}
        height={size}
        strokeWidth={2}
        className={className}
      />
    );
  }
  const [type, arrow] = name.split('-') as [string, 'down' | 'up' | undefined];
  return (
    <FxFileIcon
      type={type.toUpperCase() as FxFileType}
      arrow={arrow}
      size={size}
      className={className}
    />
  );
}

interface FxFileIconProps extends Omit<SVGProps<SVGSVGElement>, 'type'> {
  type: FxFileType;
  /** Down for download or export, up for upload. */
  arrow?: 'down' | 'up';
  size?: FxIconSize;
}

/**
 * A page with its type on a tag (PDF, CSV, SOA, BANK) and an optional arrow,
 * as in the playbook's Other Actions table ("Export CSV" = CSV file + down).
 */
export function FxFileIcon({
  type,
  arrow,
  size = 18,
  className,
  ...rest
}: FxFileIconProps) {
  const tagWidth = type.length > 3 ? 15 : 12;
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      data-fx-file={type}
      {...rest}
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h7" />
      <path d="M14 2v6h6" />
      <path d="M20 8v4" />
      <rect
        x={1}
        y={10}
        width={tagWidth}
        height={7}
        rx={1.5}
        fill="currentColor"
        stroke="none"
      />
      <text
        x={1 + tagWidth / 2}
        y={15.4}
        textAnchor="middle"
        fontSize={type.length > 3 ? 4.4 : 5}
        fontWeight={700}
        fill="var(--fx-surface, #fff)"
        stroke="none"
      >
        {type}
      </text>
      {arrow === 'down' && <path d="M19 15v7m-3-3 3 3 3-3" />}
      {arrow === 'up' && <path d="M19 22v-7m-3 3 3-3 3 3" />}
    </svg>
  );
}
