'use client';

/**
 * Wizard error screens E1-E5 (owner-approved mock `meta-leads-error-states`).
 * Each names the cause in plain words and offers the one way forward.
 */
import { AlertTriangle, ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { UseLeadCaptureWizard } from '@/hooks/use-lead-capture-wizard';
import { GuidePlayer, LEADS_ACCESS_GUIDE } from './guide-player';

export function WizardProblem({ wizard }: { wizard: UseLeadCaptureWizard }) {
  const { problem } = wizard;
  if (!problem) return null;
  const pageName = wizard.state.pages?.find((p) => p.id === wizard.state.pageId)?.name ?? 'This Page';

  let text = problem.message;
  let action: { label: string; run: () => void } = { label: 'Try again', run: wizard.dismissProblem };
  let guide = false;

  switch (problem.screen) {
    case 'permission-declined': // E1
      text = 'Facebook did not give permission to read leads. Leave every permission ticked on the Facebook screen.';
      action = { label: 'Try again', run: () => void wizard.signIn() };
      break;
    case 'no-pages': // E2
      text = 'No Page was shared. You need to be an admin of the Page that runs the ads.';
      action = { label: 'Try again', run: () => void wizard.signIn() };
      break;
    case 'leads-access': // E3
      text = `${pageName} only lets chosen apps read its leads. Add this app under Leads Access.`;
      action = { label: 'Check again', run: () => void wizard.reloadForms() };
      guide = true;
      break;
    case 'page-in-use': // E4
      text = `${pageName} is already connected to another account.`;
      action = { label: 'Choose another Page', run: wizard.dismissProblem };
      break;
    case 'reconnect': // E5
      text = 'Facebook stopped sharing leads for this Page. Sign in again to reconnect it.';
      action = { label: 'Sign in again', run: () => void wizard.signIn() };
      break;
    default:
      break;
  }

  return (
    <div role="alert" className="flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning/5 p-3">
      <p className="flex items-start gap-2 text-sm text-foreground">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <span>{text}</span>
      </p>
      {guide ? <GuidePlayer frames={LEADS_ACCESS_GUIDE} /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" onClick={action.run} disabled={Boolean(wizard.busy)}>
          {action.label}
        </Button>
        {guide ? (
          <Button variant="outline" asChild>
            <a href="https://business.facebook.com/settings/" target="_blank" rel="noopener noreferrer">
              <ExternalLink aria-hidden />
              Open Meta Business settings
            </a>
          </Button>
        ) : null}
      </div>
    </div>
  );
}
