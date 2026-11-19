'use client';

/**
 * Foundryx UIUX switch only (slice W1-CONTACTS): the done toasts of the
 * Contacts list, with Undo wherever the existing API can really reverse the
 * change (playbook "When something is done"; answers.md: Undo stays 5 s for
 * changes that are not deletes).
 *
 * - Assign: Undo puts each contact back on its old assignee (bulk assign).
 * - Add / Remove tags: Undo takes off only the tags it added, or puts back
 *   only the tags it removed (bulk tags).
 * - Move lifecycle: no Undo. A move runs the stage machine (allowed edges,
 *   conditions, automations), so moving back is not guaranteed to be allowed
 *   or to undo what the move set off.
 * - Save as segment: Undo deletes the segment just saved.
 *
 * A change where some contacts failed keeps the switch-off report, which
 * names each failed contact with its reason.
 */
import { useCallback } from 'react';
import type { BulkResult, ContactListItem } from '@/types/omnichannel';
import { ApiError } from '@/lib/api-client';
import { toast } from '@/lib/toast';
import {
  reportBulkResult,
  type UseContactBulkResult,
} from '@/hooks/use-contact-bulk';
import { contactSegmentService } from '@/services/contact-segment-service';
import {
  fxAssignUndoPlan,
  fxBulkDoneWhat,
  fxContacts,
  fxTagsUndoPlan,
  useFxActorName,
  type FxBulkKind,
} from './contacts-fx';

/** Undo window for changes that are not deletes (answers.md). */
export const FX_UNDO_SECONDS = 5;

const VERB_PAST: Record<FxBulkKind, string> = {
  assign: 'assigned',
  'add-tags': 'tagged',
  'remove-tags': 'untagged',
  lifecycle: 'moved',
};

export interface FxBulkDoneInput {
  kind: FxBulkKind;
  rows: ContactListItem[];
  result: BulkResult;
  /** Assignee name, tag names or stage label, for the toast's words. */
  target: string | string[] | null;
  /** What the change sent, for its Undo. */
  sent:
    | { kind: 'assign'; assigneeUserId: string | null }
    | { kind: 'tags'; mode: 'add' | 'remove'; tagIds: string[] }
    | { kind: 'lifecycle' };
  reload: () => void;
}

function describe(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : 'Could not undo the change.';
}

export function useContactsFxDone(
  bulk: UseContactBulkResult,
  workspaceId: string | null,
  refreshSegments: () => void,
) {
  const actor = useFxActorName();

  const reportBulk = useCallback(
    ({ kind, rows, result, target, sent, reload }: FxBulkDoneInput) => {
      const nameFor = (id: string) => rows.find((r) => r.id === id)?.name ?? id;
      if (result.failed.length > 0 || result.ok.length === 0) {
        reportBulkResult(result, VERB_PAST[kind], nameFor);
        return;
      }
      const okRows = rows.filter((r) => result.ok.includes(r.id));
      let undo: (() => Promise<void>) | undefined;
      if (sent.kind === 'assign') {
        const plan = fxAssignUndoPlan(rows, result.ok, sent.assigneeUserId);
        if (plan.length) {
          undo = async () => {
            for (const step of plan)
              await bulk.assign(step.ids, step.assigneeUserId);
          };
        }
      } else if (sent.kind === 'tags') {
        const plan = fxTagsUndoPlan(rows, result.ok, sent.mode, sent.tagIds);
        if (plan.length) {
          undo = async () => {
            for (const step of plan)
              await bulk.tags(step.ids, step.mode, step.tagIds);
          };
        }
      }
      const runUndo = undo;
      toast.fxDone({
        what: fxBulkDoneWhat(kind, okRows, target),
        byWhom: actor,
        ...(runUndo
          ? {
              seconds: FX_UNDO_SECONDS,
              undo: () => {
                void runUndo()
                  .then(() =>
                    toast.fxDone({
                      what: `${okRows.length === 1 ? okRows[0].name : fxContacts(okRows.length)} put back`,
                      byWhom: actor,
                    }),
                  )
                  .catch((error: unknown) => toast.error(describe(error)))
                  .finally(reload);
              },
            }
          : {}),
      });
    },
    [actor, bulk],
  );

  const reportSegmentSaved = useCallback(
    (name: string, created: unknown) => {
      const id = (created as { id?: unknown } | null)?.id;
      const undo =
        workspaceId && typeof id === 'string'
          ? () => {
              void contactSegmentService
                .remove(workspaceId, id)
                .then(() =>
                  toast.fxDone({
                    what: `Segment "${name}" removed`,
                    byWhom: actor,
                  }),
                )
                .catch((error: unknown) => toast.error(describe(error)))
                .finally(refreshSegments);
            }
          : undefined;
      toast.fxDone({
        what: `Segment "${name}" saved`,
        byWhom: actor,
        ...(undo ? { seconds: FX_UNDO_SECONDS, undo } : {}),
      });
    },
    [actor, workspaceId, refreshSegments],
  );

  return { reportBulk, reportSegmentSaved };
}
