'use client';

/**
 * Hosted "Connect a lead source" wizard (plan 64 L-C, AC-64-06..08, 11..18,
 * 20..23). Opened from a single-use URL (gateway connect session or a staff
 * user). One question per step; answered steps fold to one line and reopen on
 * click. White-label: the tenant's own name and logo only (AC-64-11).
 */
import { useState, type ReactElement } from 'react';
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { BrandMark } from '@/components/platform/branding';
import { ClampedText } from '@/components/platform/clamped-text';
import { useLeadCaptureWizard, type UseLeadCaptureWizard } from '@/hooks/use-lead-capture-wizard';
import {
  WIZARD_STEPS,
  answerLabel,
  currentStep,
  isAnswered,
  progressPercent,
  visibleSteps,
  type WizardStepKey,
} from '@/lib/lead-capture-wizard';
import { cn } from '@/lib/utils';
import type { PublicBranding } from '@/types/branding';
import { DoneScreen } from './components/done-screen';
import { WizardProblem } from './components/wizard-problem';
import {
  ChannelStep,
  FieldsStep,
  FormsStep,
  PageStep,
  SignInStep,
  StepAction,
  TestStep,
} from './components/wizard-steps';

function brandingOf(name: string, logoUrl: string | null): PublicBranding {
  return {
    isBranded: true,
    tenantName: name,
    appName: null,
    slogan: null,
    logoUrl,
    faviconUrl: null,
    illustrationUrl: null,
    tokens: null,
    version: 0,
  };
}

const BODIES: Record<WizardStepKey, (props: { wizard: UseLeadCaptureWizard }) => ReactElement | null> = {
  channel: ChannelStep,
  signin: SignInStep,
  page: PageStep,
  forms: FormsStep,
  fields: FieldsStep,
  test: TestStep,
};

export default function LeadCaptureConnectPage() {
  const wizard = useLeadCaptureWizard();
  const [expanded, setExpanded] = useState<WizardStepKey | null>(null);
  const { phase, context, state } = wizard;

  if (phase === 'expired') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center">
          <h1 className="font-heading text-lg font-semibold text-foreground">This link has expired</h1>
          <p className="mt-2 text-sm text-muted-foreground">Start again from your app.</p>
        </div>
      </main>
    );
  }

  const current = currentStep(state);
  const channelLabel = context?.channels.find((c) => c.key === state.channel)?.label;

  return (
    <main className="flex min-h-screen justify-center bg-background px-4 py-6 sm:py-10">
      <div className="flex w-full max-w-2xl flex-col gap-4">
        <header className="flex items-center justify-between gap-3">
          {context ? (
            <BrandMark branding={brandingOf(context.branding.name, context.branding.logoUrl)} />
          ) : (
            <Skeleton className="h-7 w-32" />
          )}
          <Button type="button" variant="ghost" mode="icon" aria-label="Close" onClick={wizard.close}>
            <X />
          </Button>
        </header>

        <section className="rounded-xl border border-border bg-card p-4 sm:p-6">
          {phase === 'opening' || !context ? (
            <div className="flex flex-col gap-3" aria-busy="true">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : phase === 'done' && wizard.done ? (
            <DoneScreen done={wizard.done} onDone={wizard.close} />
          ) : (
            <div className="flex flex-col gap-4">
              <h1 className="font-heading text-lg font-semibold text-foreground">Connect a lead source</h1>
              <div className="flex flex-col gap-2">
                <Progress value={progressPercent(state)} aria-label="Setup progress" className="h-1.5" />
                <ol className="flex justify-between gap-1 text-xs">
                  {WIZARD_STEPS.map((s) => (
                    <li
                      key={s.key}
                      className={cn(
                        s.key === current ? 'font-medium text-foreground' : 'hidden text-muted-foreground sm:block',
                        isAnswered(s.key, state) && 'sm:text-foreground',
                      )}
                    >
                      {s.label}
                    </li>
                  ))}
                </ol>
              </div>

              <ol className="flex flex-col gap-2">
                {visibleSteps(state).map((step) => {
                  const Body = BODIES[step.key];
                  const answer = answerLabel(step.key, state, { channelLabel });
                  const open = step.key === current || expanded === step.key;
                  if (answer && !open) {
                    return (
                      <li key={step.key}>
                        <div
                          role="button"
                          tabIndex={0}
                          aria-label={`${step.question}: ${answer.text}`}
                          onClick={() => setExpanded(step.key)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              setExpanded(step.key);
                            }
                          }}
                          className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-border px-3 py-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                          <ClampedText text={step.question} lines={1} className="min-w-0 flex-1 text-sm text-muted-foreground" />
                          <ClampedText
                            text={[answer.text, answer.note].filter(Boolean).join(' ')}
                            lines={1}
                            className="max-w-[50%] rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-foreground"
                          />
                        </div>
                      </li>
                    );
                  }
                  return (
                    <li key={step.key} className="flex flex-col gap-3 rounded-lg border border-primary/40 p-3 sm:p-4">
                      <button
                        type="button"
                        className="flex items-center gap-2 text-start"
                        onClick={() => setExpanded(expanded === step.key ? null : step.key)}
                        disabled={!answer}
                      >
                        {answer ? <ChevronDown className="size-4 text-muted-foreground" aria-hidden /> : null}
                        <span className="font-medium text-foreground">{step.question}</span>
                      </button>
                      <Body wizard={wizard} />
                    </li>
                  );
                })}
              </ol>

              <WizardProblem wizard={wizard} />

              {current === null ? (
                <StepAction label="Finish setup" onClick={() => void wizard.finish()} busy={wizard.busy === 'finish'} />
              ) : null}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
