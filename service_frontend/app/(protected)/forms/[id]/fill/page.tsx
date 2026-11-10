'use client';

/** Internal fill page (plan sprint-3/01 D19) - any authenticated tenant user
 * (filling ≠ administering; deliberately NO forms.* permission gate). Serves
 * only the PUBLISHED version (D9).
 *
 * Plan sprint-4/04: `?revision={submissionId}` edits + resubmits an existing
 * Draft revision (pre-filled from its cloned answers, pinned to its version),
 * then redirects back to the submission detail. */
import { useEffect } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { CheckCircle2, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FormRenderer } from '@/components/platform/form-renderer';
import { useFormFill } from '@/hooks/use-form-fill';

export default function FormFillPage() {
  const params = useParams();
  const search = useSearchParams();
  const router = useRouter();
  const formId = String(params.id);
  const revisionId = search.get('revision') ?? undefined;
  const fill = useFormFill(formId, { revisionId });

  // A saved revision returns to its submission detail (history shows the chain).
  useEffect(() => {
    if (fill.isRevision && fill.submitted && fill.resubmittedId) {
      router.replace(`/forms/${formId}/submissions/${fill.resubmittedId}`);
    }
  }, [fill.isRevision, fill.submitted, fill.resubmittedId, formId, router]);

  if (fill.loading) {
    return (
      <Container width="fixed">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (fill.notAvailable || !fill.view) {
    return (
      <Container width="fixed">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">
            {fill.isRevision ? 'This revision is not open for editing.' : 'This form is not available.'}
          </p>
          <Button variant="outline" size="sm" asChild>
            <Link href={fill.isRevision ? `/forms/${formId}` : '/'}>
              {fill.isRevision ? 'Back to form' : 'Back home'}
            </Link>
          </Button>
        </div>
      </Container>
    );
  }

  if (fill.submitted) {
    return (
      <Container width="fixed">
        <div
          className="flex flex-col items-center gap-3 py-24 text-center"
          data-testid="fill-success"
        >
          <CheckCircle2 className="size-10 text-success" />
          <p className="text-base font-medium">
            {fill.isRevision ? 'Your revision was submitted.' : 'Your response was submitted.'}
          </p>
          {!fill.isRevision && (
            <Button variant="outline" size="sm" onClick={fill.reset}>
              Submit another response
            </Button>
          )}
        </div>
      </Container>
    );
  }

  return (
    <Container width="fixed">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 py-6">
        <div>
          {fill.isRevision && (
            <Badge variant="primary" appearance="light" size="sm" className="mb-2">
              Revision
            </Badge>
          )}
          <h2 className="font-heading text-xl font-semibold text-foreground">{fill.view.name}</h2>
          {fill.view.description && (
            <p className="mt-1 text-sm text-muted-foreground">{fill.view.description}</p>
          )}
        </div>
        <FormRenderer
          definition={fill.view.definition}
          mode="fill"
          answers={fill.answers}
          onChange={fill.setAnswers}
          errors={fill.errors}
          paged={fill.view.paged}
          submitting={fill.submitting}
          onSubmit={fill.submit}
          submitLabel={fill.isRevision ? 'Submit revision' : undefined}
        />
      </div>
    </Container>
  );
}
