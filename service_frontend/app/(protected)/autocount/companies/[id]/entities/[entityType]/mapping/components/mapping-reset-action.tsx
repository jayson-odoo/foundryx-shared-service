'use client';

/**
 * "Reset to preset" as ONE reusable pair (sprint-5/12, Group B - AC-12-21/22/
 * 23, fix round AC-12-27): the `ResourceAction` descriptor plus the dialog it
 * opens. Both mapping surfaces mount THIS - the standalone
 * `/mapping` editor (`MappingEditorView`) and the DB task editor's Mapping tab
 * (`TaskEditorView`, the only way a document entity's mapping is reached) - so
 * the gating (`autocount.companies.manage` AND a server-derived `hasPreset`),
 * the dirty-guard behaviour (the shell hides every form action while editing)
 * and the post-apply hydration (`applyView`, never a second GET) can never
 * drift between the two.
 */
import { useMemo, useState, type ReactNode } from 'react';
import { RotateCcw } from 'lucide-react';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { AutocountMappingView } from '@/types/autocount';
import { AC_COMPANIES_MANAGE } from '../../../../../../components/autocount-meta';
import { MappingResetDialog } from './mapping-reset-dialog';

export interface UseMappingResetActionArgs {
  companyId: string;
  entityType: string;
  /** Server-derived (D5) - never guessed from the entity type. False hides
   *  the action entirely (foolproof-UI: only offer what will work). */
  hasPreset: boolean;
  /** Hydrate the caller's table from the view the APPLY returned. */
  onApplied: (view: AutocountMappingView) => void;
}

export interface MappingResetActionResult<T> {
  /** Drop into the surface's `ResourceFormConfig.actions`. */
  action: ResourceAction<T>;
  /** Render beside the surface's `ResourceForm`. */
  dialog: ReactNode;
}

export function useMappingResetAction<T>({
  companyId,
  entityType,
  hasPreset,
  onApplied,
}: UseMappingResetActionArgs): MappingResetActionResult<T> {
  const [open, setOpen] = useState(false);

  // D6: a plain `run` (no `confirm`, no `deferred`) - the dialog itself IS
  // the preview, and the applied rows stay editable afterwards.
  const action = useMemo<ResourceAction<T>>(
    () => ({
      id: 'reset-to-preset',
      label: 'Reset to preset',
      icon: RotateCcw,
      surfaces: { form: true },
      permission: AC_COMPANIES_MANAGE,
      isVisible: () => hasPreset,
      run: () => setOpen(true),
    }),
    [hasPreset],
  );

  const dialog = (
    <MappingResetDialog
      open={open}
      onOpenChange={setOpen}
      companyId={companyId}
      entityType={entityType}
      onApplied={onApplied}
    />
  );

  return { action, dialog };
}
