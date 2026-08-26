'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Code2, Info, LoaderCircleIcon, Mail } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { Label } from '@/components/ui/label';
import { ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { emailLogService } from '@/services/email-log-service';
import type { EmailLogDetail } from '@/types/templates';
import { EMAIL_LOG_PATH, EMAIL_STATUS_REGISTRY, emailLogDetailHref } from './email-status';
import { useEmailLogActions } from './use-email-log-actions';

function OverviewRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 md:grid-cols-[200px_1fr] md:items-center md:gap-4">
      <Label className="text-sm text-muted-foreground">{label}</Label>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function BodyTab({ email }: { email: EmailLogDetail }) {
  const [view, setView] = useState<'rendered' | 'html' | 'text'>('rendered');
  return (
    <div className="flex flex-col gap-3 py-2">
      <div className="flex items-center gap-1">
        <Button type="button" size="sm" variant={view === 'rendered' ? 'primary' : 'outline'} onClick={() => setView('rendered')}>
          Rendered
        </Button>
        <Button type="button" size="sm" variant={view === 'html' ? 'primary' : 'outline'} onClick={() => setView('html')} data-testid="body-view-html">
          Raw HTML
        </Button>
        <Button type="button" size="sm" variant={view === 'text' ? 'primary' : 'outline'} onClick={() => setView('text')} data-testid="body-view-text">
          Plain text
        </Button>
      </div>

      {view === 'rendered' && (
        <div className="flex justify-center rounded-md border border-input bg-zinc-100 p-4">
          {/* Sandboxed (D14): stored HTML never executes scripts in the app
              origin; links stay clickable and open in a new tab. */}
          <iframe
            title="Email body"
            data-testid="email-body-frame"
            sandbox="allow-popups allow-popups-to-escape-sandbox"
            srcDoc={`<base target="_blank">${email.htmlBody}`}
            className="h-[640px] w-[600px] max-w-full border-0 bg-white shadow-sm"
          />
        </div>
      )}
      {view === 'html' && (
        <pre className="max-h-[640px] overflow-auto rounded-md bg-muted px-3 py-2 font-mono text-xs">
          {email.htmlBody}
        </pre>
      )}
      {view === 'text' && (
        <pre className="max-h-[640px] overflow-auto whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm">
          {email.textBody}
        </pre>
      )}
    </div>
  );
}

export function EmailDetailView({ emailId }: { emailId: string }) {
  const [email, setEmail] = useState<EmailLogDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const actions = useEmailLogActions();
  const { formatDateTime } = useDatetime();
  const form = useForm();

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    emailLogService.get(emailId).then((row) => {
      if (cancelled) return;
      setEmail(row);
      setIsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [emailId, reloadKey]);

  const config = useMemo<ResourceFormConfig<EmailLogDetail> | null>(() => {
    if (!email) return null;
    return {
      breadcrumb: [
        { label: 'Settings' },
        { label: 'Email log', href: EMAIL_LOG_PATH },
        { label: email.subject },
      ],
      backHref: EMAIL_LOG_PATH,
      title: email.subject,
      subtitle: `To ${email.toEmail}`,
      tabs: [
        {
          id: 'overview',
          label: 'Overview',
          icon: Info,
          render: () => (
            <div className="flex flex-col gap-4 py-2">
              <OverviewRow label="To">{email.toEmail}</OverviewRow>
              <OverviewRow label="Subject">{email.subject}</OverviewRow>
              <OverviewRow label="Template">
                <code className="text-xs">{email.templateKey}</code>
              </OverviewRow>
              <OverviewRow label="Status">
                <StatusBadge status={email.status} registry={EMAIL_STATUS_REGISTRY} size="sm" />
              </OverviewRow>
              <OverviewRow label="Attempts">{email.attempts}</OverviewRow>
              <OverviewRow label="Created">{formatDateTime(email.createdAt)}</OverviewRow>
              <OverviewRow label="Sent">
                {email.sentAt ? formatDateTime(email.sentAt) : '-'}
              </OverviewRow>
              <OverviewRow label="Next attempt">
                {email.nextAttemptAt ? formatDateTime(email.nextAttemptAt) : '-'}
              </OverviewRow>
              <OverviewRow label="Fallback connection used">
                {email.usedFallback ? 'Yes - tenant connection failed, platform took over' : 'No'}
              </OverviewRow>
              <OverviewRow label="Connection">
                {email.connectionId ? <code className="text-xs">{email.connectionId}</code> : '-'}
              </OverviewRow>
              {email.lastError && (
                <OverviewRow label="Last error">
                  <pre
                    data-testid="email-last-error"
                    className="whitespace-pre-wrap rounded-md bg-destructive/5 px-3 py-2 font-mono text-xs text-destructive"
                  >
                    {email.lastError}
                  </pre>
                </OverviewRow>
              )}
            </div>
          ),
        },
        {
          id: 'body',
          label: 'Body',
          icon: Mail,
          render: () => <BodyTab email={email} />,
        },
      ],
      initialTabId: 'overview',
      actions,
      actionRows: [email],
      // Read-only surface - outbox rows are historical facts (D14: no Edit toggle).
      editable: false,
      isDirty: false,
      onSave: () => true,
      onCancel: () => setReloadKey((k) => k + 1),
      // House Form invariant: circular N / M prev-next record-nav (?ctx=&i=).
      recordNav: {
        fetchAt: (query, index) =>
          emailLogService.getAt(query, index).then((r) => ({
            recordId: r.email?.id ?? null,
            total: r.total,
          })),
        buildHref: (recordId, ctx, index) => emailLogDetailHref(recordId, { ctx, index }),
      },
    };
  }, [actions, email, formatDateTime]);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (!email || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Email not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={EMAIL_LOG_PATH}>Back to email log</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}

// Icon kept for potential raw-view affordances (referenced by tests).
export const __icons = { Code2 };
