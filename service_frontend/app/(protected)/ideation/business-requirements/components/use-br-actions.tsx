'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api-client';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { StatusGraph } from '@/types/status-engine';
import type {
  BusinessRequirementDetail,
  BusinessRequirementStatus,
} from '@/types/business-requirement';
import type { FormFieldErrors } from '@/types/forms';
import { businessRequirementService } from '@/services/business-requirement-service';

/** The BR promote edge id (Gate 0, AC-BI-34) — the ONE edge gated by the
 * separate `.promote` permission. A code contract, not a tenant-editable key. */
const PROMOTE_EDGE_ID = 'br-tr-promote';

export interface UseBrActionsHandlers {
  /** Refresh the form with the moved BR (status + answers). */
  onChanged: (br: BusinessRequirementDetail) => void;
  /** A promote refused for missing required fields (AC-BI-34b) — surface the
   * per-field map inline on the Details tab. */
  onFieldErrors: (errors: FormFieldErrors) => void;
}

interface Detail422 {
  fieldErrors?: Record<string, string>;
  message?: string;
}

function is422Detail(detail: unknown): detail is Detail422 {
  return typeof detail === 'object' && detail !== null;
}

/**
 * BR lifecycle + promote action registry (AC-BI-34) — GRAPH-DRIVEN, cloning the
 * tenant-console pattern one record at a time. Each outgoing edge from the BR's
 * current status becomes a form action whose label is the bare TARGET status
 * name (EMS per-row-state-move mandate — no "Move to" prefix). The `br-tr-promote`
 * edge additionally carries the `.promote` permission (the shell hides it for a
 * `.manage`-only user; the server 403 is the real boundary). Firing posts the
 * explicit status move; a promote refused for incomplete answers (AC-BI-34b)
 * surfaces the friendly message + inline field errors.
 */
export function useBrActions(
  br: BusinessRequirementDetail | null,
  handlers: UseBrActionsHandlers,
): ResourceAction<BusinessRequirementDetail>[] {
  const { onChanged, onFieldErrors } = handlers;
  const [graph, setGraph] = useState<StatusGraph | null>(null);

  // The BR entity's edge graph drives the buttons. Fail quiet — Delete stays.
  useEffect(() => {
    let cancelled = false;
    businessRequirementService
      .statusGraph()
      .then((g) => !cancelled && setGraph(g))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return useMemo<ResourceAction<BusinessRequirementDetail>[]>(() => {
    if (!graph || !br) return [];
    const statusById = new Map(graph.statuses.map((s) => [s.id, s]));
    const current = graph.statuses.find((s) => s.key === br.status);
    if (!current) return [];

    const edges = graph.transitions
      .filter((t) => t.fromStatusId === current.id)
      .sort((a, b) => a.sortOrder - b.sortOrder);

    return edges.map((edge) => {
      const target = statusById.get(edge.toStatusId);
      const targetKey = (target?.key ?? '') as BusinessRequirementStatus;
      const isPromote = edge.id === PROMOTE_EDGE_ID;
      return {
        id: `transition-${edge.id}`,
        // Bare target status name (user mandate — no "Move to" prefix).
        label: target?.label ?? edge.label,
        icon: ArrowRight,
        surfaces: { form: true },
        // The promote edge is the only one gated by the separate .promote perm;
        // every other BR edge rides .manage (the form's editPermission).
        ...(isPromote
          ? { permission: 'ideation.business_requirements.promote' as const }
          : {}),
        run: async (_rows, rt) => {
          try {
            const updated = await businessRequirementService.setStatus(br.id, targetKey);
            onChanged(updated);
            toast.success(`Moved to ${target?.label ?? targetKey}.`);
            rt.reload();
          } catch (e) {
            if (e instanceof ApiError && e.status === 422 && is422Detail(e.detail)) {
              const detail = e.detail;
              if (detail.fieldErrors) onFieldErrors(detail.fieldErrors);
              toast.error(detail.message ?? 'Add the required fields before promoting.');
              return;
            }
            toast.error(e instanceof Error ? e.message : 'Could not move the requirement.');
          }
        },
      } satisfies ResourceAction<BusinessRequirementDetail>;
    });
  }, [graph, br, onChanged, onFieldErrors]);
}
