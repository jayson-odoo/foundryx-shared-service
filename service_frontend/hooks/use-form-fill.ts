'use client';

/** Internal fill state (plan sprint-3/01 D15/D19) — loads the PUBLISHED
 * version, holds answers, submits through the service (422 → per-field error
 * map for the renderer). Any authenticated user may fill (filling ≠
 * administering).
 *
 * Plan sprint-4/04: with `revisionId`, the page instead edits an existing
 * Draft revision — it loads that submission, pre-fills its cloned answers,
 * renders against ITS pinned version, and resubmits into the same row (R3,
 * "rides the existing submit/transition flow"). */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { FormSubmitError, formService } from '@/services/form-service';
import type { FormAnswers, FormFieldErrors, FormFillView } from '@/types/forms';

export interface UseFormFillOptions {
  /** When set, edit + resubmit this Draft revision instead of a fresh fill. */
  revisionId?: string;
}

export interface UseFormFillResult {
  view: FormFillView | null;
  loading: boolean;
  notAvailable: boolean;
  /** True in revision mode — the page heads it as a revision + redirects on save. */
  isRevision: boolean;
  /** The resubmitted submission id once a revision is saved (for redirect). */
  resubmittedId: string | null;
  answers: FormAnswers;
  setAnswers: (answers: FormAnswers) => void;
  errors: FormFieldErrors;
  submitting: boolean;
  submitted: boolean;
  submit: (visible: FormAnswers) => Promise<void>;
  reset: () => void;
}

export function useFormFill(formId: string, options: UseFormFillOptions = {}): UseFormFillResult {
  const { revisionId } = options;
  const [view, setView] = useState<FormFillView | null>(null);
  const [loading, setLoading] = useState(true);
  const [notAvailable, setNotAvailable] = useState(false);
  const [answers, setAnswers] = useState<FormAnswers>({});
  const [errors, setErrors] = useState<FormFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [resubmittedId, setResubmittedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        if (revisionId) {
          const row = await formService.getSubmission(revisionId);
          if (cancelled) return;
          if (!row || row.formId !== formId) {
            setNotAvailable(true);
            return;
          }
          const [definition, form] = await Promise.all([
            formService.versionDefinition(formId, row.versionId),
            formService.get(formId).catch(() => null),
          ]);
          if (cancelled) return;
          if (!definition) {
            setNotAvailable(true);
            return;
          }
          setView({
            formId,
            versionId: row.versionId,
            versionNumber: row.versionNumber,
            name: form?.name ?? 'Revision',
            description: form?.description ?? null,
            definition,
            paged: (form?.displayMode ?? 'paged') === 'paged',
          });
          setAnswers(row.answers);
        } else {
          const v = await formService.fill(formId);
          if (cancelled) return;
          if (!v) setNotAvailable(true);
          else setView(v);
        }
      } catch {
        if (!cancelled) setNotAvailable(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [formId, revisionId]);

  const submit = useCallback(
    async (visible: FormAnswers) => {
      setSubmitting(true);
      setErrors({});
      try {
        if (revisionId) {
          const row = await formService.resubmitRevision(revisionId, visible);
          setResubmittedId(row.id);
        } else {
          await formService.submit(formId, visible);
        }
        setSubmitted(true);
      } catch (e) {
        if (e instanceof FormSubmitError) {
          setErrors(e.fieldErrors);
        } else {
          toast.error(e instanceof Error ? e.message : 'Submission failed.');
        }
      } finally {
        setSubmitting(false);
      }
    },
    [formId, revisionId],
  );

  const reset = useCallback(() => {
    setAnswers({});
    setErrors({});
    setSubmitted(false);
  }, []);

  return {
    view,
    loading,
    notAvailable,
    isRevision: !!revisionId,
    resubmittedId,
    answers,
    setAnswers,
    errors,
    submitting,
    submitted,
    submit,
    reset,
  };
}
