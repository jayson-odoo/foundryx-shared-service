'use client';

/** Public (anonymous) fill page (plan sprint-3/02, D11). Pre-auth, branded by
 * the public layout; tenant resolved from the subdomain frontend-side and
 * carried in the service path. Renders the SAME `FormRenderer` as the internal
 * fill — this surface IS the future embed contract (website builder, F5). */
import { useMemo } from 'react';
import { useParams } from 'next/navigation';
import { CheckCircle2, LoaderCircleIcon, AlertCircle } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FormRenderer } from '@/components/platform/form-renderer';
import { usePublicFormFill } from '@/hooks/use-public-form-fill';
import { deriveTenantSlug } from '@/lib/tenant';

export default function PublicFormFillPage() {
  const params = useParams();
  const formSlug = String(params.slug);
  const tenantSlug = useMemo(
    () => (typeof window === 'undefined' ? 'default' : deriveTenantSlug(window.location.hostname)),
    [],
  );
  const fill = usePublicFormFill(tenantSlug, formSlug);

  const shell = (body: React.ReactNode) => (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">{body}</div>
  );

  if (fill.loading) {
    return shell(
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>,
    );
  }

  // Uniform "not available" — never disclose whether the form, tenant, or
  // published state is the reason (no enumeration, D11).
  if (fill.notFound || !fill.view) {
    return shell(
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <AlertCircle className="size-10 text-muted-foreground" />
        <p className="text-base font-medium">This form isn’t available.</p>
      </div>,
    );
  }

  if (fill.view.state !== 'open' || !fill.view.definition) {
    return shell(
      <div className="flex flex-col items-center gap-3 py-24 text-center" data-testid="form-closed">
        <p className="font-heading text-xl font-semibold text-foreground">{fill.view.name}</p>
        <p className="text-sm text-muted-foreground">
          {fill.view.message ?? 'This form is not accepting responses right now.'}
        </p>
      </div>,
    );
  }

  if (fill.submitted) {
    return shell(
      <div className="flex flex-col items-center gap-3 py-24 text-center" data-testid="fill-success">
        <CheckCircle2 className="size-10 text-success" />
        <p className="text-base font-medium">Your response was submitted.</p>
        <Button variant="outline" size="sm" onClick={fill.reset}>
          Submit another response
        </Button>
      </div>,
    );
  }

  return shell(
    <>
      <div>
        <h1 className="font-heading text-xl font-semibold text-foreground">{fill.view.name}</h1>
        {fill.view.description && (
          <p className="mt-1 text-sm text-muted-foreground">{fill.view.description}</p>
        )}
      </div>

      {fill.rateLimited && (
        <Alert variant="warning" appearance="light">
          <AlertIcon>
            <AlertCircle />
          </AlertIcon>
          <AlertTitle>{fill.rateLimited}</AlertTitle>
        </Alert>
      )}

      <FormRenderer
        definition={fill.view.definition}
        mode="fill"
        answers={fill.answers}
        onChange={fill.setAnswers}
        errors={fill.errors}
        paged={fill.view.paged}
        submitting={fill.submitting}
        onSubmit={fill.submit}
      />

      {/* Honeypot — visually + accessibly hidden; a real user never fills it,
          a naive bot does → server rejects (D12). Not `display:none` (some bots
          skip those); off-screen + aria-hidden + no tab stop. */}
      <div aria-hidden="true" className="absolute -left-[9999px] top-0 h-0 w-0 overflow-hidden">
        <label>
          Company
          <input
            type="text"
            name={fill.view.honeypotField}
            tabIndex={-1}
            autoComplete="off"
            value={fill.honeypot}
            onChange={(e) => fill.setHoneypot(e.target.value)}
          />
        </label>
      </div>
    </>,
  );
}
