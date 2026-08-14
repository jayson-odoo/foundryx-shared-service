import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import type { ListQuery } from '@/types/resource';
import type { ResourceAction } from '@/components/platform/resource-list/types';

export interface FormTab {
  id: string;
  label: string;
  icon?: LucideIcon;
  /** Render tab content; `editing` flips fields read ↔ editable (global edit). */
  render: (ctx: { editing: boolean }) => ReactNode;
}

export interface BreadcrumbStep {
  label: string;
  href?: string;
}

/** Record-nav wiring (the form re-runs the carried list query at index±1). */
export interface RecordNavConfig {
  fetchAt: (query: ListQuery, index: number) => Promise<{ recordId: string | null; total: number }>;
  /** Build the neighbour's form href from id + (encoded) ctx + index. */
  buildHref: (recordId: string, ctx: string, index: number) => string;
}

export interface ResourceFormConfig<T> {
  breadcrumb: BreadcrumbStep[];
  /** Where the breadcrumb "back" + Back button return to (the list). */
  backHref: string;
  backLabel?: string;
  title: string;
  /** Sub-identifier under the title. Accepts a node so it can carry a link
   * (e.g. a clickable trace id) - a bare string is still valid (string ⊂ node). */
  subtitle?: ReactNode;
  /** Identity avatar node (e.g. initials). */
  avatar?: ReactNode;
  tabs: FormTab[];
  /** Tab to open on mount (defaults to the first tab). */
  initialTabId?: string;
  /** Form-surface actions for the "…" menu. */
  actions: ResourceAction<T>[];
  /** The record, wrapped for action runtime ([] when creating). */
  actionRows: T[];
  /**
   * Refresh the loaded record after a mutating form-surface action (e.g. a
   * Test that flips status). Without it, `runtime.reload` is a no-op on the
   * form (plan 06 - the connection Health card went stale otherwise).
   */
  onReload?: () => void;

  /** Whether the Edit toggle is offered (false for create/new). */
  editable: boolean;
  /** Permission key required to show the Edit toggle (UX gate; backend enforces). */
  editPermission?: string;
  /** Start in edit mode (create page, or ?edit=1). */
  initialEditing?: boolean;
  /** RHF dirty flag - gates the unsaved-changes guard. */
  isDirty: boolean;
  /** Commit edits. Return false to stay in edit mode (validation failed). */
  onSave: () => Promise<boolean> | boolean;
  /** Revert edits (RHF reset). */
  onCancel: () => void;

  recordNav?: RecordNavConfig;

  /**
   * Embedded (form-in-form) mode - when true the form renders WITHOUT the
   * breadcrumb and uses `onBack` + `inlineNav` instead of URL navigation, so it
   * can live inside a parent form's tab (MasterDetail). Same chrome otherwise
   * (title, icon tabs, record-nav, FormRow fields).
   */
  embedded?: boolean;
  /** Back button as an in-place action (vs the URL Link) - used when embedded. */
  onBack?: () => void;
  /** In-memory record-nav (vs the URL RecordNav) - used when embedded. */
  inlineNav?: {
    index: number;
    total: number;
    onPrev: () => void;
    onNext: () => void;
  };
}
