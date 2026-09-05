'use client';

/** One submission's detail state (plan sprint-3/01 D18) - the row, its
 * PINNED version's definition (faithful re-render forever, D9) and the
 * graph-driven transitions it can fire (D15). Plan sprint-4/04 adds the
 * revision chain, the form's `allowRevisions` flag and the Revise action. */
import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { formService, type FormSubmissionGraph } from '@/services/form-service';
import type { FormDocument, FormSubmissionRow } from '@/types/forms';

export interface UseFormSubmissionResult {
  submission: FormSubmissionRow | null;
  definition: FormDocument | null;
  graph: FormSubmissionGraph | null;
  /** Whether the form permits revising a frozen submission (R2). */
  allowRevisions: boolean;
  /** The full revision chain for this submission's group, newest first (R3). */
  revisions: FormSubmissionRow[];
  /** Resolved from the graph - true while answers are still editable (Draft). */
  isActive: boolean;
  loading: boolean;
  notFound: boolean;
  busy: boolean;
  fireTransition: (transitionId: string) => Promise<void>;
  /** Clone this frozen submission into a new Draft revision; returns its id. */
  revise: () => Promise<string | null>;
}

export function useFormSubmission(formId: string, submissionId: string): UseFormSubmissionResult {
  const [submission, setSubmission] = useState<FormSubmissionRow | null>(null);
  const [definition, setDefinition] = useState<FormDocument | null>(null);
  const [graph, setGraph] = useState<FormSubmissionGraph | null>(null);
  const [allowRevisions, setAllowRevisions] = useState(false);
  const [revisions, setRevisions] = useState<FormSubmissionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const row = await formService.getSubmission(submissionId);
        if (cancelled) return;
        if (!row || row.formId !== formId) {
          setNotFound(true);
          return;
        }
        setSubmission(row);
        const [doc, g, form, chain] = await Promise.all([
          formService.versionDefinition(formId, row.versionId),
          formService.submissionGraph(formId),
          // allowRevisions is form-level; tolerate a perm/load miss (Revise just
          // stays hidden - the backend is the real gate).
          formService.get(formId).catch(() => null),
          formService.submissionRevisions(formId, row.submissionGroupId).catch(() => []),
        ]);
        if (cancelled) return;
        setDefinition(doc);
        setGraph(g);
        setAllowRevisions(form?.allowRevisions ?? false);
        setRevisions(chain.length ? chain : [row]);
      } catch {
        if (!cancelled) setNotFound(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [formId, submissionId]);

  const fireTransition = useCallback(
    async (transitionId: string) => {
      setBusy(true);
      try {
        const updated = await formService.transitionSubmission(submissionId, transitionId);
        setSubmission(updated);
        // The status moved - the chain's labels/flags may have shifted too.
        const chain = await formService
          .submissionRevisions(formId, updated.submissionGroupId)
          .catch(() => [updated]);
        setRevisions(chain.length ? chain : [updated]);
        toast.success(`Moved to ${updated.statusLabel}.`);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Transition failed.');
      } finally {
        setBusy(false);
      }
    },
    [formId, submissionId],
  );

  const revise = useCallback(async (): Promise<string | null> => {
    setBusy(true);
    try {
      const draft = await formService.revise(submissionId);
      toast.success('Revision started - edit and resubmit.');
      return draft.id;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not start a revision.');
      return null;
    } finally {
      setBusy(false);
    }
  }, [submissionId]);

  const isActive = graph?.statuses.find((s) => s.id === submission?.statusId)?.isActive ?? false;

  return {
    submission,
    definition,
    graph,
    allowRevisions,
    revisions,
    isActive,
    loading,
    notFound,
    busy,
    fireTransition,
    revise,
  };
}
