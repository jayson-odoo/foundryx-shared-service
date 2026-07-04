'use client';

/**
 * Form runtime renderer (plan sprint-3/01, D6/D7/D14/D18) — the ONE component
 * serving every fill surface: internal fill, author Preview, public fill
 * (slice 2), and read-only submission view (`mode='read'`, D18). It walks the
 * published `FormDocument` (Page → Section → Field), drives conditional
 * visibility live off the CURRENT answers, recomputes computed fields, and
 * gates wizard navigation with the client validation mirror (the SERVER stays
 * the boundary — `onSubmit` receives only the VISIBLE answers).
 *
 * Foolproof-UI: only the doc's own labels / placeholders / helpText render —
 * never instructional copy. Mobile-first: 2-column sections collapse under
 * `md:`, inputs are full width, wizard nav stacks acceptably at 375px.
 */
import { useEffect, useMemo, useState } from 'react';
import { fieldByKey, fieldVisible, isDisplayField, sectionVisible } from '@/lib/form-doc';
import {
  computeValue,
  pageOfKey,
  validateAll,
  validateField,
  validatePage,
  visibleAnswers,
  visibleFacts,
} from '@/lib/form-validate';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { RequiredMark } from '@/components/platform/resource-form/form-row';
import type {
  FormAnswers,
  FormAnswerValue,
  FormDocument,
  FormField,
  FormFieldErrors,
  FormSection,
} from '@/types/forms';
import { FieldInput } from './field-input';
import { FieldRead } from './field-read';
import { SubmissionContext, type FileBlobFetcher } from './submission-context';

export interface FormRendererProps {
  definition: FormDocument;
  /** 'fill' = interactive; 'read' = submission view (inputs → rendered values). */
  mode: 'fill' | 'read';
  answers: FormAnswers;
  onChange?: (answers: FormAnswers) => void;
  /** Server 422 map — merged over client errors, auto-jumps to first error's page. */
  errors?: FormFieldErrors;
  /** Wizard steps (true) vs one scrolling page (false). Single-page docs render
   * no wizard chrome either way. */
  paged?: boolean;
  onSubmit?: (visible: FormAnswers) => void | Promise<void>;
  submitting?: boolean;
  submitLabel?: string;
  /** Read-mode only — lets uploaded-file chips fetch the authed serve route. */
  submissionId?: string;
  /** Session-bound blob fetcher for uploaded-file chips (staff = apiFetchBlob,
   * portal = portalApiFetchBlob). The renderer NEVER imports the staff client
   * itself — without a fetcher the chip is a plain label (Cluster E fix). */
  fileFetcher?: FileBlobFetcher;
}

export function FormRenderer({
  definition,
  mode,
  answers,
  onChange,
  errors: serverErrors,
  paged = false,
  onSubmit,
  submitting = false,
  submitLabel = 'Submit',
  submissionId,
  fileFetcher,
}: FormRendererProps) {
  const pages = definition.pages ?? [];
  const isWizard = mode === 'fill' && paged && pages.length > 1;

  const [pageIndex, setPageIndex] = useState(0);
  // Client errors raised by Next/Submit; merged with the server map for display.
  const [clientErrors, setClientErrors] = useState<FormFieldErrors>({});

  // Visibility runs off the VISIBLE-set facts (not the raw answer map) so a
  // retained hidden value can't keep a downstream field shown — matches the
  // server's submit-time visibility (D14).
  const facts = useMemo(() => visibleFacts(definition, answers), [definition, answers]);
  const mergedErrors = useMemo(
    () => ({ ...clientErrors, ...(serverErrors ?? {}) }),
    [clientErrors, serverErrors],
  );

  // Server 422 → jump to the first errored field's page (D14).
  useEffect(() => {
    const firstKey = serverErrors ? Object.keys(serverErrors)[0] : undefined;
    if (!firstKey) return;
    const target = pageOfKey(definition, firstKey);
    if (target >= 0) setPageIndex(target);
  }, [serverErrors, definition]);

  const setAnswer = (key: string, value: FormAnswerValue) => {
    const nextAnswers = { ...answers, [key]: value };
    onChange?.(nextAnswers);
    // Live per-field validation: surface FORMAT errors (decimal places, integer,
    // email…) as the user types, but leave "required" for submit/transition so a
    // half-typed/cleared field doesn't nag. Clears this field's stale errors
    // (its own key + nested `key.row.col` for table/repeater cells).
    setClientErrors((prev) => {
      const cleaned: FormFieldErrors = {};
      for (const [k, v] of Object.entries(prev)) {
        if (k !== key && !k.startsWith(`${key}.`)) cleaned[k] = v;
      }
      const field = fieldByKey(definition, key);
      if (field) {
        const fieldErrors: FormFieldErrors = {};
        validateField(field, nextAnswers, fieldErrors);
        for (const [k, v] of Object.entries(fieldErrors)) {
          if (v !== 'This field is required.') cleaned[k] = v;
        }
      }
      return cleaned;
    });
  };

  const goNext = () => {
    const pageErrors = validatePage(definition, pageIndex, answers);
    if (Object.keys(pageErrors).length > 0) {
      setClientErrors((prev) => ({ ...prev, ...pageErrors }));
      return;
    }
    setPageIndex((i) => Math.min(pages.length - 1, i + 1));
  };

  const goBack = () => setPageIndex((i) => Math.max(0, i - 1));

  const handleSubmit = async () => {
    const all = validateAll(definition, answers);
    if (Object.keys(all).length > 0) {
      setClientErrors(all);
      const firstKey = Object.keys(all)[0];
      const target = pageOfKey(definition, firstKey);
      if (isWizard && target >= 0) setPageIndex(target);
      return;
    }
    setClientErrors({});
    await onSubmit?.(visibleAnswers(definition, answers));
  };

  const renderedPages = isWizard ? [pages[pageIndex]] : pages;

  return (
    <SubmissionContext.Provider value={{ submissionId, fetchFile: fileFetcher }}>
    <div className="space-y-6">
      {isWizard && (
        <StepIndicator pages={pages} current={pageIndex} />
      )}

      {renderedPages.map((page) => (
        <div key={page.id} className="space-y-6">
          {page.title && !isWizard && (
            <h2 className="font-heading text-lg font-semibold text-foreground">{page.title}</h2>
          )}
          {page.sections.map((section) =>
            sectionVisible(section, facts) ? (
              <SectionBlock
                key={section.id}
                section={section}
                facts={facts}
                mode={mode}
                answers={answers}
                errors={mergedErrors}
                onChange={setAnswer}
              />
            ) : null,
          )}
        </div>
      ))}

      {mode === 'fill' && (
        <FormNav
          isWizard={isWizard}
          pageIndex={pageIndex}
          lastIndex={pages.length - 1}
          submitting={submitting}
          submitLabel={submitLabel}
          hasSubmit={Boolean(onSubmit)}
          onBack={goBack}
          onNext={goNext}
          onSubmit={handleSubmit}
        />
      )}
    </div>
    </SubmissionContext.Provider>
  );
}

// ---- navigation ----

interface FormNavProps {
  isWizard: boolean;
  pageIndex: number;
  lastIndex: number;
  submitting: boolean;
  submitLabel: string;
  hasSubmit: boolean;
  onBack: () => void;
  onNext: () => void;
  onSubmit: () => void;
}

function FormNav({
  isWizard,
  pageIndex,
  lastIndex,
  submitting,
  submitLabel,
  hasSubmit,
  onBack,
  onNext,
  onSubmit,
}: FormNavProps) {
  const onLastPage = pageIndex >= lastIndex;
  return (
    <div className="flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-between">
      {isWizard && pageIndex > 0 ? (
        <Button type="button" variant="outline" onClick={onBack} disabled={submitting}>
          Back
        </Button>
      ) : (
        <span className="hidden sm:block" />
      )}
      {isWizard && !onLastPage ? (
        <Button type="button" onClick={onNext}>
          Next
        </Button>
      ) : (
        hasSubmit && (
          <Button type="button" onClick={onSubmit} disabled={submitting}>
            {submitting ? 'Submitting…' : submitLabel}
          </Button>
        )
      )}
    </div>
  );
}

// ---- step indicator ----

function StepIndicator({ pages, current }: { pages: FormDocument['pages']; current: number }) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-muted-foreground">
        {pages[current]?.title || `Step ${current + 1} of ${pages.length}`}
      </p>
      <div className="flex gap-1.5" aria-hidden="true">
        {pages.map((page, i) => (
          <span
            key={page.id}
            className={cn(
              'h-1.5 flex-1 rounded-full',
              i <= current ? 'bg-primary' : 'bg-muted',
            )}
          />
        ))}
      </div>
    </div>
  );
}

// ---- section ----

interface SectionBlockProps {
  section: FormSection;
  facts: Record<string, unknown>;
  mode: 'fill' | 'read';
  answers: FormAnswers;
  errors: FormFieldErrors;
  onChange: (key: string, value: FormAnswerValue) => void;
}

function SectionBlock({ section, facts, mode, answers, errors, onChange }: SectionBlockProps) {
  const visibleFields = section.fields.filter(
    (field) => isDisplayField(field) || fieldVisible(field, section, facts),
  );
  if (visibleFields.length === 0 && !section.title && !section.description) return null;

  return (
    <section className="space-y-4">
      {(section.title || section.description) && (
        <div className="space-y-1">
          {section.title && (
            <h3 className="font-heading text-base font-semibold text-foreground">{section.title}</h3>
          )}
          {section.description && (
            <p className="text-sm text-muted-foreground">{section.description}</p>
          )}
        </div>
      )}
      <div
        className={cn(
          'grid grid-cols-1 gap-x-6 gap-y-4',
          section.twoColumn && 'md:grid-cols-2',
        )}
      >
        {visibleFields.map((field) => (
          <FieldBlock
            key={field.id}
            field={field}
            mode={mode}
            answers={answers}
            errors={errors}
            onChange={onChange}
          />
        ))}
      </div>
    </section>
  );
}

// ---- field ----

interface FieldBlockProps {
  field: FormField;
  mode: 'fill' | 'read';
  answers: FormAnswers;
  errors: FormFieldErrors;
  onChange: (key: string, value: FormAnswerValue) => void;
}

function FieldBlock({ field, mode, answers, errors, onChange }: FieldBlockProps) {
  if (isDisplayField(field)) return <DisplayBlock field={field} />;

  const key = field.key ?? field.id;
  const id = `ff-${key}`;
  const error = errors[key];
  const value = answers[key];
  const computed = field.type === 'computed' ? computeValue(field, answers) : undefined;

  // Composite fields whose own errors live under nested keys (`key.row.subKey`).
  const composite = field.type === 'repeater' || field.type === 'address' || field.type === 'table';

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} variant="primary">
        {field.label}
        {field.required && mode === 'fill' && <RequiredMark />}
      </Label>
      {mode === 'read' ? (
        <div className="text-sm text-foreground">
          <FieldRead field={field} value={value} computed={computed} />
        </div>
      ) : (
        <FieldInput
          field={field}
          id={id}
          value={value}
          computed={computed}
          errors={errors}
          invalid={Boolean(error) && !composite}
          onChange={(v) => onChange(key, v)}
        />
      )}
      {field.helpText && (
        <p className="text-xs text-muted-foreground">{field.helpText}</p>
      )}
      {mode === 'fill' && error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

function DisplayBlock({ field }: { field: FormField }) {
  if (field.type === 'divider') {
    return <hr className="col-span-full border-border" />;
  }
  if (field.type === 'heading') {
    const level = field.heading?.level ?? 2;
    const sizes: Record<number, string> = { 1: 'text-xl', 2: 'text-lg', 3: 'text-base' };
    return (
      <div className="col-span-full">
        <p className={cn('font-heading font-semibold text-foreground', sizes[level])}>{field.label}</p>
      </div>
    );
  }
  // paragraph
  return <p className="col-span-full text-sm text-muted-foreground">{field.label}</p>;
}
