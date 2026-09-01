'use client';

import { useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  LoaderCircle,
  PlugZap,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
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
import { Label } from '@/components/ui/label';
import { Form } from '@/components/ui/form';
import { ConfigurationTab } from '@/app/(protected)/settings/integrations/components/connection-form-fields';
import { useStorageMigration, type MigrationStep } from '@/hooks/use-storage-migration';
import type { Job } from '@/types/jobs';

export interface StorageMigrationWizardProps {
  open: boolean;
  onClose: () => void;
  /** Called with the enqueued job once a migration starts. */
  onStarted: (job: Job) => void;
}

const STEP_ORDER: MigrationStep[] = ['configure', 'test', 'confirm'];
const STEP_LABELS: Record<MigrationStep, string> = {
  configure: 'New bucket',
  test: 'Test',
  confirm: 'Confirm',
};

/**
 * Storage-migration wizard (sprint-4/10 AC-10-18). Three steps: configure the
 * new bucket B (reusing the connect wizard's `fields()`-driven form) → a live,
 * non-destructive Test (Start stays gated until it passes) → a typed-confirm on
 * the bucket name before the destructive Start. Responsive: single-column,
 * scrollable body - usable at 375px and 1280px.
 */
export function StorageMigrationWizard({ open, onClose, onStarted }: StorageMigrationWizardProps) {
  const m = useStorageMigration(open);
  const [confirmError, setConfirmError] = useState(false);

  const currentIndex = STEP_ORDER.indexOf(m.step);

  const goNext = async () => {
    if (m.step === 'configure') {
      // Full per-provider validation before advancing to Test - surfaces field
      // errors on the visible config step.
      if (!(await m.validateConfigure())) return;
      m.next();
    } else if (m.step === 'test') {
      if (!m.testResult?.ok) return;
      m.next();
    }
  };

  const doStart = async () => {
    if (!m.canStart) {
      setConfirmError(true);
      return;
    }
    try {
      const job = await m.start();
      if (job) {
        toast.success('Storage migration started - track it in the Jobs drawer.');
        onStarted(job);
        onClose();
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not start the migration.');
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-5 py-4">
          <DialogTitle>Migrate storage</DialogTitle>
          <DialogDescription>
            Move every existing asset to a new bucket with no downtime.
          </DialogDescription>
        </DialogHeader>

        {/* Step indicator - wraps on narrow (375px) screens. */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-5 py-3">
          {STEP_ORDER.map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <span
                className={
                  i <= currentIndex
                    ? 'flex size-6 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground'
                    : 'flex size-6 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground'
                }
              >
                {i + 1}
              </span>
              <span
                className={
                  i === currentIndex
                    ? 'text-sm font-medium text-foreground'
                    : 'text-sm text-muted-foreground'
                }
              >
                {STEP_LABELS[s]}
              </span>
              {i < STEP_ORDER.length - 1 && (
                <ArrowRight className="size-3.5 text-muted-foreground" />
              )}
            </div>
          ))}
        </div>

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
              <p className="text-sm text-muted-foreground">
                Verify a write and read-back against{' '}
                <span className="font-medium text-foreground">{m.targetName || 'the new bucket'}</span>{' '}
                before migrating.
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => void m.runTest()}
                disabled={m.testing}
              >
                {m.testing ? (
                  <LoaderCircle className="size-4 animate-spin" />
                ) : (
                  <PlugZap className="size-4" />
                )}
                Test bucket
              </Button>
              {m.testResult && (
                <div
                  className={
                    m.testResult.ok
                      ? 'flex items-start gap-2 rounded-lg border border-green-600/30 bg-green-600/5 p-3'
                      : 'flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3'
                  }
                >
                  {m.testResult.ok ? (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-green-600" />
                  ) : (
                    <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
                  )}
                  <p
                    className={
                      m.testResult.ok
                        ? 'text-sm text-foreground'
                        : 'text-sm text-destructive'
                    }
                  >
                    {m.testResult.message}
                  </p>
                </div>
              )}
            </div>
          )}

          {m.step === 'confirm' && (
            <div className="space-y-4">
              <div className="rounded-lg border p-4 text-sm">
                <div className="flex items-center justify-between gap-3 py-1">
                  <span className="text-muted-foreground">New bucket</span>
                  <span className="font-medium">{m.targetName}</span>
                </div>
                <div className="flex items-center justify-between gap-3 py-1">
                  <span className="text-muted-foreground">Provider</span>
                  <span className="font-medium">{m.provider?.title ?? '-'}</span>
                </div>
                <p className="mt-2 text-muted-foreground">
                  Every existing asset is copied to the new bucket, then references
                  are switched over. New uploads land on the new bucket immediately;
                  the old bucket is retired but never deleted.
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="migration-confirm">
                  Type <span className="font-semibold text-foreground">{m.targetName}</span> to confirm
                </Label>
                <Input
                  id="migration-confirm"
                  value={m.confirmValue}
                  onChange={(e) => {
                    m.setConfirmValue(e.target.value);
                    setConfirmError(false);
                  }}
                  placeholder={m.targetName}
                  autoComplete="off"
                />
                {confirmError && (
                  <p className="text-xs text-destructive">
                    The name doesn&apos;t match.
                  </p>
                )}
              </div>
            </div>
          )}
        </DialogBody>

        <DialogFooter className="flex-row items-center justify-between gap-2 border-t px-5 py-4">
          <Button
            type="button"
            variant="ghost"
            onClick={m.step === 'configure' ? onClose : m.back}
            disabled={m.starting}
          >
            {m.step === 'configure' ? (
              'Cancel'
            ) : (
              <>
                <ArrowLeft className="size-4" /> Back
              </>
            )}
          </Button>
          {m.step === 'confirm' ? (
            <Button type="button" onClick={() => void doStart()} disabled={!m.canStart || m.starting}>
              {m.starting ? <LoaderCircle className="size-4 animate-spin" /> : null}
              Start migration
            </Button>
          ) : (
            <Button
              type="button"
              onClick={() => void goNext()}
              disabled={
                (m.step === 'configure' && !m.canAdvanceFromConfigure) ||
                (m.step === 'test' && !m.testResult?.ok)
              }
            >
              Next <ArrowRight className="size-4" />
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
