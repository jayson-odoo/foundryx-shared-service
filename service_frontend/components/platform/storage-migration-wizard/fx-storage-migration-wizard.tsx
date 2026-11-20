'use client';

/**
 * The storage migration wizard under the Foundryx UIUX switch (slice
 * W3-DOCS): the same three steps over the same hook (`useStorageMigration`),
 * so the Test gate and every request are today's. The last step is the
 * playbook's typed confirm: type the new bucket's name; "Start migration"
 * stays greyed with its reason until the name matches (the hook's own rule,
 * `canStart`), and nothing is sent before. A started migration says what and
 * who; it shows in the Jobs sheet, so no "track it in the Jobs drawer" line.
 * No Undo: a migration is stopped from its job, not undone.
 */
import { useId, useState } from 'react';
import { ArrowLeft, ArrowRight, CheckCircle2, LoaderCircle, PlugZap, XCircle } from 'lucide-react';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Form } from '@/components/ui/form';
import { FX_FIELD_LABEL } from '@/components/fx/fields';
import { ConfigurationTab } from '@/app/(protected)/settings/integrations/components/connection-form-fields';
import { useStorageMigration, type MigrationStep } from '@/hooks/use-storage-migration';
import { useFxActorName } from '@/components/platform/document-drive/fx-drive-words';
import type { StorageMigrationWizardProps } from './storage-migration-wizard';

const STEP_ORDER: MigrationStep[] = ['configure', 'test', 'confirm'];
const STEP_LABELS: Record<MigrationStep, string> = {
  configure: 'New bucket',
  test: 'Test',
  confirm: 'Confirm',
};

export const FX_BUCKET_WHY = 'Type the bucket name to confirm.';

export function FxStorageMigrationWizard({ open, onClose, onStarted }: StorageMigrationWizardProps) {
  const m = useStorageMigration(open);
  const byWhom = useFxActorName();
  const [failure, setFailure] = useState<string | null>(null);
  const whyId = useId();
  const inputId = useId();
  const currentIndex = STEP_ORDER.indexOf(m.step);

  const goNext = async () => {
    if (m.step === 'configure') {
      if (!(await m.validateConfigure())) return;
      m.next();
    } else if (m.step === 'test') {
      if (!m.testResult?.ok) return;
      m.next();
    }
  };

  const doStart = async () => {
    if (!m.canStart || m.starting) return;
    setFailure(null);
    try {
      const job = await m.start();
      if (job) {
        toast.fxDone({ what: `Storage migration to ${m.targetName} started`, byWhom });
        onStarted(job);
        onClose();
      }
    } catch (e) {
      setFailure(e instanceof Error && e.message ? e.message : "Couldn't start the migration.");
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="border-b border-(--fx-line) px-5 py-4">
          <DialogTitle>Migrate storage</DialogTitle>
          <DialogDescription>Every stored file moves to a new bucket, with no downtime.</DialogDescription>
        </DialogHeader>

        <ol aria-label="Steps" className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-(--fx-line) px-5 py-3">
          {STEP_ORDER.map((s, i) => (
            <li key={s} className="flex items-center gap-2" aria-current={i === currentIndex ? 'step' : undefined}>
              <span
                className={cn(
                  'flex size-6 items-center justify-center rounded-(--fx-r-pill) text-sm font-semibold tabular-nums',
                  i <= currentIndex ? 'bg-(--fx-ink) text-(--fx-surface)' : 'bg-(--fx-surface-2) text-(--fx-ink-3)',
                )}
              >
                {i + 1}
              </span>
              <span className={cn('text-sm', i === currentIndex ? 'font-semibold text-(--fx-ink)' : 'text-(--fx-ink-2)')}>
                {STEP_LABELS[s]}
              </span>
              {i < STEP_ORDER.length - 1 && <ArrowRight className="size-3.5 text-(--fx-ink-3)" aria-hidden="true" />}
            </li>
          ))}
        </ol>

        <DialogBody className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {m.step === 'configure' && (
            <Form {...m.form}>
              <ConfigurationTab
                form={m.form}
                editing
                creating
                providers={m.providers}
                provider={m.provider}
                onProviderChange={m.onProviderChange}
                connection={null}
              />
            </Form>
          )}

          {m.step === 'test' && (
            <div className="space-y-4">
              <p className="text-sm text-(--fx-ink-2)">
                A test file is written to{' '}
                <span className="font-semibold text-(--fx-ink)">{m.targetName || 'the new bucket'}</span> and read
                back.
              </p>
              <Button type="button" variant="fx-quiet" onClick={() => void m.runTest()} disabled={m.testing}>
                {m.testing ? <LoaderCircle className="size-4 animate-spin" /> : <PlugZap className="size-4" />}
                Test bucket
              </Button>
              {m.testResult && (
                <div
                  role="status"
                  className={cn(
                    'flex items-start gap-2 rounded-(--fx-r-m) border p-3 text-sm',
                    m.testResult.ok ? 'border-(--fx-line) text-(--fx-ink)' : 'border-(--fx-act) text-(--fx-ink)',
                  )}
                >
                  {m.testResult.ok ? (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-(--fx-ok)" aria-hidden="true" />
                  ) : (
                    <XCircle className="mt-0.5 size-4 shrink-0 text-(--fx-act)" aria-hidden="true" />
                  )}
                  <p>{m.testResult.message}</p>
                </div>
              )}
            </div>
          )}

          {m.step === 'confirm' && (
            <div className="space-y-4">
              <dl className="grid gap-1 rounded-(--fx-r-m) border border-(--fx-line) p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-(--fx-ink-2)">New bucket</dt>
                  <dd className="font-semibold">{m.targetName}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-(--fx-ink-2)">Provider</dt>
                  <dd className="font-semibold">{m.provider?.title ?? '-'}</dd>
                </div>
                <p className="mt-2 text-(--fx-ink-2)">
                  Every stored file is copied, then switched over. New uploads go to the new bucket at once; the old
                  bucket is kept, never deleted.
                </p>
              </dl>
              <div className="flex flex-col gap-1.5">
                <label htmlFor={inputId} className={FX_FIELD_LABEL}>
                  {`Type "${m.targetName}"`}
                </label>
                <Input
                  id={inputId}
                  value={m.confirmValue}
                  onChange={(e) => m.setConfirmValue(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              {failure && (
                <p role="alert" className="text-sm font-semibold text-(--fx-act)">
                  {failure}
                </p>
              )}
            </div>
          )}
        </DialogBody>

        <DialogFooter className="flex-row items-start justify-between gap-2 border-t border-(--fx-line) px-5 py-4">
          <Button
            type="button"
            variant="fx-quiet"
            onClick={m.step === 'configure' ? onClose : m.back}
            disabled={m.starting}
          >
            {m.step === 'configure' ? (
              'Cancel'
            ) : (
              <>
                <ArrowLeft className="size-4" aria-hidden="true" /> Back
              </>
            )}
          </Button>
          {m.step === 'confirm' ? (
            <div className="flex flex-col items-end">
              <Button
                type="button"
                variant="fx-main"
                aria-disabled={m.canStart ? undefined : true}
                aria-describedby={m.canStart ? undefined : whyId}
                className={cn(!m.canStart && 'cursor-not-allowed opacity-45')}
                onClick={() => void doStart()}
              >
                {m.starting ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : null}
                Start migration
              </Button>
              {!m.canStart && (
                <p id={whyId} className="mt-1 text-end text-sm font-semibold text-(--fx-ink-2)">
                  {FX_BUCKET_WHY}
                </p>
              )}
            </div>
          ) : (
            <Button
              type="button"
              variant="fx-quiet"
              onClick={() => void goNext()}
              disabled={(m.step === 'configure' && !m.canAdvanceFromConfigure) || (m.step === 'test' && !m.testResult?.ok)}
            >
              Next <ArrowRight className="size-4" aria-hidden="true" />
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
