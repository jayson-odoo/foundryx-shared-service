'use client';

/**
 * "Continuous sync" card on a finished respond.io migration (plan 52,
 * AC-SYNC-50..53). Component -> `useMigrationSync` -> service; the card holds
 * no fetch. Times go through `useDatetime()`.
 */
import { useState } from 'react';
import { Check, Copy, LoaderCircle } from 'lucide-react';
import type { MigrationSyncItem } from '@/types/respondio-migration';
import { useCan } from '@/hooks/use-can';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { useDatetime } from '@/hooks/use-datetime';
import { useMigrationSync } from '@/hooks/use-migration-sync';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import { StatusBadge } from '@/components/platform/status-badge';
import { MigrationFailuresTable } from './migration-failures-table';
import { SYNC_PAUSED_REASON_TEXT, SYNC_STATUS_REGISTRY } from './sync-status';

const STOP_ACTION: ResourceAction<MigrationSyncItem> = {
  id: 'stop-sync',
  label: 'Stop syncing (cutover)',
  tone: 'destructive',
  surfaces: { form: true },
  confirm: {
    title: 'Stop syncing?',
    description: 'One final sync runs, then syncing ends.',
    confirmLabel: 'Stop syncing',
  },
  run: () => undefined,
};

export function MigrationSyncCard({
  jobId,
  workspaceId,
}: {
  jobId: string;
  workspaceId: string;
}) {
  const { can } = useCan();
  const canManage = can('omnichannel_migration.manage');
  const { formatDateTime } = useDatetime();
  const {
    sync,
    loaded,
    busy,
    webhookUrl,
    webhookUnreadable,
    start,
    act,
    rotateWebhook,
  } = useMigrationSync(workspaceId, canManage);
  const [confirmingStop, setConfirmingStop] = useState(false);
  const { copyToClipboard, isCopied } = useCopyToClipboard();

  if (!loaded) return null;
  // Read-only users see nothing to start; an existing sync is still shown.
  if (!sync && !canManage) return null;

  const running = Boolean(sync?.runningJobId);
  const result = sync?.lastResult ?? null;
  const webhookVisible = Boolean(
    canManage && sync && sync.status !== 'stopped',
  );
  const showWebhook = webhookVisible && webhookUrl;

  return (
    <>
      <Card className="mt-5">
        <CardHeader>
          <CardHeading>
            <CardTitle>Continuous sync</CardTitle>
          </CardHeading>
          {sync && (
            <div className="flex items-center gap-2">
              <StatusBadge
                status={sync.status}
                registry={SYNC_STATUS_REGISTRY}
              />
              {running && (
                <LoaderCircle className="text-muted-foreground size-4 animate-spin" />
              )}
            </div>
          )}
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          {!sync && (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => void start()}
                disabled={busy}
              >
                Start syncing
              </Button>
            </div>
          )}

          {sync?.status === 'active' && (
            <p>
              {`Syncing every ${sync.intervalMinutes} min.`}
              {result && sync.lastSyncAt
                ? ` Last sync ${formatDateTime(sync.lastSyncAt)}: +${result.contactsCreated} contacts, +${result.messagesCreated} messages, ${result.errors} errors.`
                : ''}
              {sync.nextSyncAt && !running
                ? ` Next sync ${formatDateTime(sync.nextSyncAt)}.`
                : ''}
              {running ? ' Sync running.' : ''}
            </p>
          )}

          {sync?.status === 'paused' && (
            <p>
              {SYNC_PAUSED_REASON_TEXT[sync.pausedReason ?? ''] ??
                'Syncing is paused'}
              {'.'}
              {sync.lastSyncAt
                ? ` Last sync ${formatDateTime(sync.lastSyncAt)}.`
                : ''}
            </p>
          )}

          {sync?.status === 'stopping' && <p>Final sync in progress.</p>}

          {sync?.status === 'stopped' && (
            <p>
              {sync.stoppedAt
                ? `Stopped ${formatDateTime(sync.stoppedAt)}`
                : 'Stopped'}
            </p>
          )}

          {sync &&
            sync.status !== 'stopped' &&
            sync.sourceContactCount !== null && (
              <p className="text-muted-foreground">
                {`${sync.sourceContactCount} respond.io contacts.`}
                {sync.estimatedFullSweepMinutes !== null
                  ? ` Full sweep about ${sync.estimatedFullSweepMinutes} min.`
                  : ''}
              </p>
            )}

          {sync?.lastError && sync.status === 'active' && (
            <p className="text-destructive break-words">{sync.lastError}</p>
          )}

          {showWebhook && (
            <div className="flex w-full items-center gap-2">
              <Input
                readOnly
                value={webhookUrl}
                aria-label="Webhook URL"
                className="min-w-0 flex-1"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => webhookUrl && copyToClipboard(webhookUrl)}
                aria-label="Copy webhook URL"
              >
                {isCopied ? (
                  <Check className="size-4" />
                ) : (
                  <Copy className="size-4" />
                )}
                {isCopied ? 'Copied' : 'Copy'}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void rotateWebhook()}
                disabled={busy}
              >
                Rotate link
              </Button>
            </div>
          )}

          {webhookVisible && !webhookUrl && webhookUnreadable && (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void rotateWebhook()}
                disabled={busy}
              >
                Rotate link
              </Button>
            </div>
          )}

          {sync && canManage && (
            <div className="flex flex-wrap gap-2">
              {sync.status === 'active' && (
                <>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => void act('run-now')}
                    disabled={busy || running}
                  >
                    Sync now
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => void act('pause')}
                    disabled={busy}
                  >
                    Pause
                  </Button>
                </>
              )}
              {sync.status === 'paused' && (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void act('resume')}
                  disabled={busy}
                >
                  Resume
                </Button>
              )}
              {(sync.status === 'active' || sync.status === 'paused') && (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  onClick={() => setConfirmingStop(true)}
                  disabled={busy}
                >
                  Stop syncing (cutover)
                </Button>
              )}
              {sync.status === 'stopped' && (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void start()}
                  disabled={busy}
                >
                  Start syncing
                </Button>
              )}
            </div>
          )}
        </CardContent>

        <ConfirmActionDialog<MigrationSyncItem>
          pending={confirmingStop ? STOP_ACTION : null}
          rows={sync ? [sync] : []}
          onClose={() => setConfirmingStop(false)}
          onConfirm={() => void act('stop')}
        />
      </Card>
      {result && result.failureSample.length > 0 && (
        <MigrationFailuresTable
          jobId={jobId}
          rows={result.failureSample}
          totalFailures={result.errors}
          hideDownload
        />
      )}
    </>
  );
}
