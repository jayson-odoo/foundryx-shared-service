'use client';

/**
 * Portal My Submissions (plan sprint-4/06 slice 2, AC-06-03/43/08/52). Lists the
 * Profile's submissions (status + decision + optional feedback — never scores)
 * and offers a Submit action per review configuration the Profile may submit to
 * (from `submit-options`, INDEPENDENT of any existing submissions — a brand-new
 * participant still sees Submit while the window is open). A config whose window
 * is closed / not yet open renders a disabled, status-labelled Submit. Revise
 * chains revise → resubmit through the ONE FormRenderer, prefilled with the prior
 * revision's answers.
 *
 * Multiple submissions per process are allowed (AC-06-52) — Submit stays
 * available after submitting, and each submission is its own row.
 */
import { useEffect, useState } from 'react';
import { LoaderCircleIcon, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { FormRenderer } from '@/components/platform/form-renderer';
import { MySubmissionsList } from '@/components/platform/review';
import { usePortalTerminology } from '@/hooks/use-portal-terminology';
import {
  usePortalSubmissionActions,
  usePortalSubmissions,
  usePortalSubmitOptions,
} from '@/hooks/use-portal-review';
import { usePortalFilter } from '@/providers/portal-filter-provider';
import { PortalPageShell } from '../portal-page-shell';
import { toast } from 'sonner';
import type { FormAnswers, FormFieldErrors } from '@/types/forms';
import type {
  MySubmission,
  SubmitFormState,
  SubmitOption,
} from '@/types/portal-review';

interface FillTarget {
  mode: 'submit' | 'revise';
  configId?: string;
  groupId?: string;
  submissionId?: string;
  title: string;
}

/** Friendly closed/upcoming label for a window-gated Submit (foolproof-UI —
 * a status line, not how-to copy). */
function windowLabel(opt: SubmitOption): string {
  if (opt.windowState === 'closed') return 'Submissions closed';
  if (opt.windowState === 'notYetOpen') return 'Not yet open';
  return opt.name;
}

export function MySubmissionsClient() {
  const { label, labelPlural } = usePortalTerminology();
  const submissionNoun = label('submission');
  const { data: submissions, loading, error, reload } = usePortalSubmissions();
  const { data: submitOptions } = usePortalSubmitOptions();
  const actions = usePortalSubmissionActions();
  // Unfiltered → show the event/context per row (AC-06-25); filtered → it's the
  // selected event for every row, so the label is redundant.
  const { activeContextKey } = usePortalFilter();
  const showContext = !activeContextKey;

  const [target, setTarget] = useState<FillTarget | null>(null);

  const onRevise = (s: MySubmission) =>
    setTarget({
      mode: 'revise',
      groupId: s.groupId,
      configId: s.reviewConfigurationId,
      title: s.title,
    });

  return (
    <PortalPageShell
      surfaceKey="my_submissions"
      title={`My ${labelPlural('submission')}`}
    >
      {submitOptions.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {submitOptions.map((opt) => (
            <Button
              key={opt.configId}
              size="sm"
              variant="outline"
              disabled={!opt.canSubmitNow}
              title={opt.canSubmitNow ? undefined : windowLabel(opt)}
              onClick={() =>
                setTarget({ mode: 'submit', configId: opt.configId, title: opt.name })
              }
            >
              <Plus className="size-3.5" />{' '}
              {opt.canSubmitNow ? opt.name : `${opt.name} · ${windowLabel(opt)}`}
            </Button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      ) : error ? (
        <p className="py-12 text-center text-sm text-destructive">{error}</p>
      ) : (
        <MySubmissionsList
          submissions={submissions}
          onRevise={onRevise}
          submissionNoun={submissionNoun}
          showContext={showContext}
        />
      )}

      {target && (
        <SubmissionFillDialog
          target={target}
          actions={actions}
          submissionNoun={submissionNoun}
          onClose={() => setTarget(null)}
          onDone={() => {
            setTarget(null);
            reload();
          }}
        />
      )}
    </PortalPageShell>
  );
}

function SubmissionFillDialog({
  target,
  actions,
  submissionNoun,
  onClose,
  onDone,
}: {
  target: FillTarget;
  actions: ReturnType<typeof usePortalSubmissionActions>;
  submissionNoun: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [view, setView] = useState<SubmitFormState['form'] | null>(null);
  const [answers, setAnswers] = useState<FormAnswers>({});
  const [errors, setErrors] = useState<FormFieldErrors>({});
  const [loading, setLoading] = useState(true);
  const [notAvailable, setNotAvailable] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // For revise we first create the Draft clone, then resubmit into it.
  const [reviseSubmissionId, setReviseSubmissionId] = useState<string | null>(null);

  // Load the form view once on open. For revise we first read the prior
  // revision's answers (to prefill), then create the Draft clone, then load the
  // (same) submission form definition to render it seeded with those answers.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setNotAvailable(null);
      try {
        let prefill: FormAnswers = {};
        if (target.mode === 'revise' && target.groupId) {
          // Prefill from the current revision's answers (AC-06-09).
          const detail = await actions.submissionDetail(target.groupId);
          if (cancelled) return;
          prefill = detail.answers ?? {};
          const r = await actions.revise(target.groupId);
          if (cancelled) return;
          setReviseSubmissionId(r.submissionId);
        }
        if (target.configId) {
          const state = await actions.submitFormView(target.configId);
          if (cancelled) return;
          if (state.state !== 'open' || !state.form) {
            setNotAvailable(state.message ?? 'This form is not available.');
          } else {
            setView(state.form);
            setAnswers(prefill);
          }
        } else {
          setNotAvailable('This form is not available.');
        }
      } catch (e) {
        if (!cancelled) {
          setNotAvailable(e instanceof Error ? e.message : 'This form is not available.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // run once per target
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSubmit = async (visible: FormAnswers) => {
    setSubmitting(true);
    setErrors({});
    try {
      if (target.mode === 'submit' && target.configId) {
        await actions.submit(target.configId, visible);
      } else if (target.mode === 'revise' && reviseSubmissionId) {
        await actions.resubmit(reviseSubmissionId, visible);
      }
      toast.success(`${submissionNoun} submitted.`);
      onDone();
    } catch (e) {
      const detail = (e as { detail?: { fieldErrors?: FormFieldErrors } }).detail;
      if (detail?.fieldErrors) {
        setErrors(detail.fieldErrors);
      } else {
        toast.error(e instanceof Error ? e.message : 'Could not submit.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {target.mode === 'revise' ? 'Revise' : 'Submit'} · {target.title}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {target.mode === 'revise' ? 'Revise your' : 'Create a'} {submissionNoun.toLowerCase()}.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-muted-foreground">
            <LoaderCircleIcon className="size-6 animate-spin" />
          </div>
        ) : notAvailable ? (
          <p className="py-12 text-center text-sm text-muted-foreground">{notAvailable}</p>
        ) : view ? (
          <FormRenderer
            definition={view.definition}
            mode="fill"
            answers={answers}
            onChange={setAnswers}
            errors={errors}
            paged={view.paged}
            submitting={submitting}
            onSubmit={onSubmit}
            submitLabel={target.mode === 'revise' ? 'Submit revision' : undefined}
          />
        ) : (
          <p className="py-12 text-center text-sm text-muted-foreground">
            This form is not available.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
