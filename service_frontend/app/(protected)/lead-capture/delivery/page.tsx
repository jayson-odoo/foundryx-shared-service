'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Alert, AlertIcon, AlertTitle, AlertToolbar } from '@/components/ui/alert';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { leadCaptureErrorMessage, useReceivers, useRemoveReceivers } from '@/hooks/use-lead-capture';
import { leadsPullUrl } from '@/services/lead-capture-service';
import { AddReceiverDialog } from './components/add-receiver-dialog';
import { type DeliveryMode, nextDeliveryMode } from './components/delivery-mode';
import { PullOnlyPanel } from './components/pull-only-panel';
import { useReceiverList } from './components/use-receiver-list';

const SEGMENT_ON =
  'data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary';

/**
 * Lead Capture > Delivery (lane L-D, AC-64-57). The product chooses ONE way to
 * get its leads: push to its own receivers, or pull with its key. Pull only =
 * no receivers, so choosing it while receivers exist removes them (confirmed).
 */
export default function LeadCaptureDeliveryPage() {
  const receivers = useReceivers();
  const { removing, remove } = useRemoveReceivers();
  const { can } = useCan();
  const [mode, setMode] = useState<DeliveryMode | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirmPull, setConfirmPull] = useState(false);
  const [nonce, setNonce] = useState(0);

  const count = receivers.data?.length ?? 0;

  // The stored state decides the first view (receivers = push, none = pull),
  // and removing the last receiver from any menu switches to Pull only.
  const prevCount = useRef<number | null>(null);
  useEffect(() => {
    if (!receivers.data) return;
    const next = receivers.data.length;
    setMode((current) => nextDeliveryMode(current, prevCount.current, next));
    prevCount.current = next;
  }, [receivers.data]);

  const onCreate = useCallback(() => setAdding(true), []);
  const reloadReceivers = receivers.reload;
  const onChanged = useCallback(() => reloadReceivers(), [reloadReceivers]);
  const config = useReceiverList(onCreate, onChanged, nonce);

  const choose = (next: string) => {
    if (next !== 'push' && next !== 'pull') return;
    if (next === 'pull' && count > 0) {
      setConfirmPull(true);
      return;
    }
    setMode(next);
  };

  const switchToPull = async () => {
    try {
      await remove((receivers.data ?? []).map((r) => r.id));
      setMode('pull');
      toast.success('Leads are now pull only.');
    } catch (err) {
      toast.error(leadCaptureErrorMessage(err, 'Could not remove the receivers. Please try again.'));
    } finally {
      setConfirmPull(false);
      receivers.reload();
      setNonce((n) => n + 1);
    }
  };

  return (
    <RequirePermission permission="lead_capture.view">
      <Container width="fluid">
        <PageHeader />
        {receivers.error && !receivers.data ? (
          <Alert variant="destructive">
            <AlertIcon>
              <AlertCircle />
            </AlertIcon>
            <AlertTitle>{receivers.error}</AlertTitle>
            <AlertToolbar>
              <Button variant="outline" size="sm" onClick={receivers.reload}>
                Try again
              </Button>
            </AlertToolbar>
          </Alert>
        ) : (
          <div className="mt-2 flex flex-col gap-4">
            <ToggleGroup
              type="single"
              size="sm"
              variant="outline"
              value={mode ?? ''}
              onValueChange={choose}
              disabled={mode === null || !can('lead_capture.manage')}
              className="self-start"
              aria-label="Delivery"
            >
              <ToggleGroupItem value="push" className={SEGMENT_ON}>
                Push to my system
              </ToggleGroupItem>
              <ToggleGroupItem value="pull" className={SEGMENT_ON}>
                Pull only
              </ToggleGroupItem>
            </ToggleGroup>
            {mode === 'push' && <ResourceList config={config} hideHeader restoreFromCtx />}
            {mode === 'pull' && <PullOnlyPanel address={leadsPullUrl()} />}
          </div>
        )}
      </Container>

      <AddReceiverDialog
        open={adding}
        onOpenChange={setAdding}
        onAdded={() => {
          receivers.reload();
          setNonce((n) => n + 1);
        }}
      />

      <AlertDialog open={confirmPull} onOpenChange={(open) => !removing && setConfirmPull(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Switch to pull only?</AlertDialogTitle>
            <AlertDialogDescription>
              {count === 1
                ? '1 receiver will be removed. New leads will no longer be pushed to it.'
                : `${count} receivers will be removed. New leads will no longer be pushed to them.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removing}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={removing}
              onClick={(e) => {
                e.preventDefault();
                void switchToPull();
              }}
            >
              Remove receivers
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </RequirePermission>
  );
}
