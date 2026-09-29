'use client';

import { useEffect, useState } from 'react';
import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { SearchSelect } from '@/components/platform/search-select';
import type { DocFeedContractGate, DocFeedEligibleConnection, DocFeedKey, DocFeedMode, DocFeedUpdateInput } from '@/types/autocount';
import { docFeedGateWarning, docFeedLabel } from '../../components/autocount-meta';

const MODE_SEGMENT_CLASS =
  'data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary';

export interface DocFeedConfigDialogProps {
  feed: DocFeedKey;
  current: { connectionId: string | null; mode: DocFeedMode; contractGate: DocFeedContractGate | null };
  eligibleConnections: DocFeedEligibleConnection[];
  onClose: () => void;
  onSave: (input: DocFeedUpdateInput) => Promise<void>;
}

/**
 * Configure a document feed's connection + mode (AC-14-91). Mode is a
 * `ToggleGroup`, not a `SearchSelect` (the codebase's own documented
 * exception - "fixed 2-3-option micro-enums may stay plain Select" - the
 * SAME shape the Schedule tab's Push/Pull toggle already uses): Dry run and
 * Push are not merely disabled when unreachable, they are ABSENT
 * (foolproof-UI, AC-14-91) - until a connection is chosen and the consumer
 * contract gate is open, Off is the only offered value.
 */
export function DocFeedConfigDialog({
  feed,
  current,
  eligibleConnections,
  onClose,
  onSave,
}: DocFeedConfigDialogProps) {
  const [connectionId, setConnectionId] = useState<string | null>(current.connectionId);
  const [mode, setMode] = useState<DocFeedMode>(current.mode);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setConnectionId(current.connectionId);
    setMode(current.mode);
  }, [feed, current.connectionId, current.mode]);

  const gate = current.contractGate;
  const canArm = Boolean(connectionId) && gate === null;

  // A stored mode the current selection can no longer reach (connection
  // cleared, or the gate shut since it was last saved) falls back to Off
  // rather than keep an unreachable choice visibly selected.
  useEffect(() => {
    if (!canArm && mode !== 'off') setMode('off');
  }, [canArm, mode]);

  async function submit() {
    setSaving(true);
    try {
      await onSave({ connectionId, mode });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Configure - {docFeedLabel(feed)}</DialogTitle>
          <DialogDescription>Connection and mode for this document feed.</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label>Connection</Label>
              <SearchSelect
                ariaLabel="Connection"
                placeholder="Choose a connection"
                value={connectionId}
                onChange={setConnectionId}
                options={eligibleConnections.map((c) => ({
                  value: c.id,
                  label: `${c.name} - ${c.book}`,
                }))}
                emptyText="No eligible connections."
              />
            </div>
            {gate && connectionId && (
              <Alert variant="warning" appearance="light" data-testid="doc-feed-gate-warning">
                <AlertIcon>
                  <TriangleAlert />
                </AlertIcon>
                <AlertTitle>{docFeedGateWarning(gate)}</AlertTitle>
              </Alert>
            )}
            <div className="flex flex-col gap-2">
              <Label>Mode</Label>
              <ToggleGroup
                type="single"
                size="sm"
                variant="outline"
                value={mode}
                onValueChange={(value) => {
                  if (value === 'off' || value === 'dry_run' || value === 'push') setMode(value);
                }}
                aria-label="Mode"
              >
                <ToggleGroupItem value="off" className={MODE_SEGMENT_CLASS} data-testid="doc-feed-mode-off">
                  Off
                </ToggleGroupItem>
                {canArm && (
                  <ToggleGroupItem value="dry_run" className={MODE_SEGMENT_CLASS} data-testid="doc-feed-mode-dry-run">
                    Dry run
                  </ToggleGroupItem>
                )}
                {canArm && (
                  <ToggleGroupItem value="push" className={MODE_SEGMENT_CLASS} data-testid="doc-feed-mode-push">
                    Push
                  </ToggleGroupItem>
                )}
              </ToggleGroup>
            </div>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving} data-testid="doc-feed-config-save">
            {saving && <LoaderCircleIcon className="size-4 animate-spin" />}
            Save feed
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
