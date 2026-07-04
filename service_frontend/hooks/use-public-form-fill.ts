'use client';

/** Public (anonymous) fill state (plan sprint-3/02). Loads the public view by
 * (tenant slug, form slug), holds answers + the honeypot value, submits through
 * the public service. No server-side drafts (D11) — multi-page state lives here
 * until the final submit. 422 → per-field errors; 429 → a throttle notice. */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { FormSubmitError } from '@/services/form-service';
import { publicFormService } from '@/services/public-form-service';
import { RateLimitError } from '@/lib/service-errors';
import type { FormAnswers, FormFieldErrors, PublicFormView } from '@/types/forms';

export interface UsePublicFormFillResult {
  view: PublicFormView | null;
  loading: boolean;
  notFound: boolean;
  answers: FormAnswers;
  setAnswers: (answers: FormAnswers) => void;
  honeypot: string;
  setHoneypot: (value: string) => void;
  errors: FormFieldErrors;
  submitting: boolean;
  submitted: boolean;
  rateLimited: string | null;
  submit: (visible: FormAnswers) => Promise<void>;
  reset: () => void;
}

export function usePublicFormFill(tenantSlug: string, formSlug: string): UsePublicFormFillResult {
  const [view, setView] = useState<PublicFormView | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [answers, setAnswers] = useState<FormAnswers>({});
  const [honeypot, setHoneypot] = useState('');
  const [errors, setErrors] = useState<FormFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [rateLimited, setRateLimited] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    publicFormService
      .view(tenantSlug, formSlug)
      .then((v) => {
        if (cancelled) return;
        if (!v) setNotFound(true);
        else setView(v);
      })
      .catch(() => !cancelled && setNotFound(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, formSlug]);

  const submit = useCallback(
    async (visible: FormAnswers) => {
      setSubmitting(true);
      setErrors({});
      setRateLimited(null);
      try {
        await publicFormService.submit(tenantSlug, formSlug, { answers: visible, honeypot });
        setSubmitted(true);
      } catch (e) {
        if (e instanceof FormSubmitError) {
          setErrors(e.fieldErrors);
        } else if (e instanceof RateLimitError) {
          const mins = e.retryAfterSeconds ? Math.ceil(e.retryAfterSeconds / 60) : null;
          setRateLimited(
            mins ? `Too many submissions. Try again in about ${mins} minute${mins === 1 ? '' : 's'}.` : 'Too many submissions. Try again later.',
          );
        } else {
          toast.error(e instanceof Error ? e.message : 'Submission failed.');
        }
      } finally {
        setSubmitting(false);
      }
    },
    [tenantSlug, formSlug, honeypot],
  );

  const reset = useCallback(() => {
    setAnswers({});
    setHoneypot('');
    setErrors({});
    setSubmitted(false);
    setRateLimited(null);
  }, []);

  return {
    view,
    loading,
    notFound,
    answers,
    setAnswers,
    honeypot,
    setHoneypot,
    errors,
    submitting,
    submitted,
    rateLimited,
    submit,
    reset,
  };
}
