'use client';

/**
 * Shared two-pane GRADE view (plan sprint-4/06 slice 2, AC-06-05/44/48). The
 * SAME component serves staff `(protected)` and portal `(portal)` — it is fully
 * identity-agnostic (no "reviewer"/"user"/"profile" anywhere): the page supplies
 * the right service-bound `actions` + the loaded two-pane payload. Reviewer
 * isolation is a backend guarantee — this view only ever receives THIS
 * reviewer's own draft (`reviewDraft`), never another's content.
 *
 * Left pane = the read-only submission at its pinned version (the ONE
 * `FormRenderer`, `mode='read'`). Right pane = the review/rubric form fill
 * (`mode='fill'`) with Save draft + Submit review. Two-pane STACKS vertically on
 * mobile (`flex-col lg:flex-row`); each pane scrolls internally on desktop.
 *
 * Foolproof-UI: labels + the form's own copy only, no how-to text. The Submission
 * / Review nouns relabel via the terminology engine (passed in by the page).
 */
import { useState } from 'react';
import { LoaderCircleIcon, SaveIcon } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { FormRenderer } from '@/components/platform/form-renderer';
import type { FormAnswers } from '@/types/forms';
import type { ReviewSurfaceActions, ReviewTwoPane } from '@/types/portal-review';

export interface ReviewTwoPaneViewProps {
  data: ReviewTwoPane;
  actions: ReviewSurfaceActions;
  /** Relabelable nouns from the terminology engine (page supplies them). */
  submissionNoun?: string;
  reviewNoun?: string;
  /** Called after a successful submit (e.g. navigate back to the queue). */
  onSubmitted?: () => void;
  /** Session-bound blob fetcher for the read-only submission pane's file chips.
   * Staff supplies `apiFetchBlob`, portal supplies `portalApiFetchBlob` — this
   * shared component never imports the staff client (Cluster E portal fix). */
  fileFetcher?: (path: string) => Promise<Blob>;
}

export function ReviewTwoPaneView({
  data,
  actions,
  submissionNoun = 'Submission',
  reviewNoun = 'Review',
  onSubmitted,
  fileFetcher,
}: ReviewTwoPaneViewProps) {
  const [answers, setAnswers] = useState<FormAnswers>(
    data.reviewDraft?.answers ?? {},
  );
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(data.status === 'COMPLETED');

  const reviewForm = data.reviewForm;

  const saveDraft = async () => {
    setSaving(true);
    try {
      await actions.saveDraft(data.assignmentId, answers);
      toast.success('Draft saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the draft.');
    } finally {
      setSaving(false);
    }
  };

  const submit = async (visible: FormAnswers) => {
    setSubmitting(true);
    try {
      await actions.submitReview(data.assignmentId, visible);
      setDone(true);
      toast.success(`${reviewNoun} submitted.`);
      onSubmitted?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : `Could not submit the ${reviewNoun.toLowerCase()}.`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-5 lg:flex-row" data-testid="review-two-pane">
      {/* Left — read-only submission (pinned version). */}
      <section
        data-testid="submission-pane"
        className="flex min-w-0 flex-1 flex-col gap-3 rounded-xl border border-border bg-card p-4 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto"
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-medium text-mono">{submissionNoun}</h2>
          <Badge variant="secondary" appearance="light" size="sm">
            Revision {data.submission.revisionNumber}
          </Badge>
        </div>
        {data.submission.definition ? (
          <FormRenderer
            definition={data.submission.definition}
            mode="read"
            answers={data.submission.answers}
            submissionId={data.submission.id}
            fileFetcher={fileFetcher}
          />
        ) : (
          <p className="py-8 text-center text-sm text-muted-foreground">
            This {submissionNoun.toLowerCase()} is not available.
          </p>
        )}
      </section>

      {/* Right — the review/rubric form (fill) with draft-save / submit. */}
      <section
        data-testid="review-pane"
        className="flex min-w-0 flex-1 flex-col gap-3 rounded-xl border border-border bg-card p-4 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto"
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-medium text-mono">{reviewNoun}</h2>
          {done && (
            <Badge variant="success" appearance="light" size="sm">
              Submitted
            </Badge>
          )}
        </div>

        {done ? (
          <FormRenderer
            definition={reviewForm?.definition ?? { schemaVersion: 1, pages: [] }}
            mode="read"
            answers={answers}
          />
        ) : reviewForm ? (
          <>
            <FormRenderer
              definition={reviewForm.definition}
              mode="fill"
              answers={answers}
              onChange={setAnswers}
              paged={reviewForm.paged}
              submitting={submitting}
              onSubmit={submit}
              submitLabel={`Submit ${reviewNoun.toLowerCase()}`}
            />
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={saving || submitting}
                onClick={saveDraft}
              >
                {saving ? (
                  <LoaderCircleIcon className="size-3.5 animate-spin" />
                ) : (
                  <SaveIcon className="size-3.5" />
                )}
                Save draft
              </Button>
            </div>
          </>
        ) : (
          <p className="py-8 text-center text-sm text-muted-foreground">
            This {reviewNoun.toLowerCase()} form is not available.
          </p>
        )}
      </section>
    </div>
  );
}
