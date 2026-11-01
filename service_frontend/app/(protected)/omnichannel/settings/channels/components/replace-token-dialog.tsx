'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useDatetime } from '@/hooks/use-datetime';
import { useReplaceChannelToken } from '@/hooks/use-replace-channel-token';
import { tokenWarnings } from '@/lib/channel-token-warnings';
import { toast } from '@/lib/toast';
import type { Channel } from '@/types/omnichannel';

export interface ReplaceTokenDialogProps {
  channel: Channel;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful save so the caller can refresh its list or record. */
  onReplaced: () => void;
}

const INPUT_ID = 'replace-token-input';
const LABEL = 'Permanent access token (System User)';

/** Replace a WhatsApp channel's access token in place (plan 42, AC-42-20..22). */
export function ReplaceTokenDialog({ channel, open, onOpenChange, onReplaced }: ReplaceTokenDialogProps) {
  const { formatDate } = useDatetime();
  const { replace, saving, error, clearError } = useReplaceChannelToken(channel.id);
  const [token, setToken] = useState('');

  useEffect(() => {
    if (!open) {
      setToken('');
      clearError();
    }
  }, [open, clearError]);

  const canSave = token.trim().length > 0 && !saving;

  const save = async () => {
    if (!canSave) return;
    const result = await replace(token.trim());
    if (!result) return;
    toast.success('Token replaced.');
    tokenWarnings(result, formatDate).forEach((message) => toast.warning(message));
    onReplaced();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !(saving && !next) && onOpenChange(next)}>
      <DialogContent className="w-full max-w-[460px]">
        <DialogHeader>
          <DialogTitle>Replace token</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-1.5">
          <label htmlFor={INPUT_ID} className="text-sm text-muted-foreground">
            {LABEL}
          </label>
          <Input
            id={INPUT_ID}
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              if (error) clearError();
            }}
            aria-invalid={error ? true : undefined}
          />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={save} disabled={!canSave}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
