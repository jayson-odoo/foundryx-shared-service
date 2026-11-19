'use client';

/**
 * The mint dialog with the Foundryx UIUX switch on (slice W2-WS, gap audit
 * "Secrets shown once"). Same two steps and the same request as the dialog
 * with the switch off (`useApiKeys().mint(name)`); what changes is how it
 * looks and reads:
 * - The red action follows what is typed ("Mint Production server key") and,
 *   with no name yet, is greyed with its reason under it.
 * - A refused mint says why under the action, not as a toast.
 * - The new key shows in full only here, in a read-only monospace field with
 *   Copy beside it and one warning line; "Done" closes the dialog and the key
 *   is forgotten (never kept in state, storage, a toast or the page after).
 */
import { useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  FxActionError,
  useFxActionError,
} from '@/components/fx/actions/action-error';
import { FxMainAction } from '@/components/fx/actions/main-action';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { FxSecretOnce } from '@/components/fx/fields';
import type { MintApiKeyDialogProps } from './mint-api-key-dialog';
import { useApiKeys } from './use-api-keys';
import { useFxUserName } from './use-fx-user-name';

const LABEL = 'text-sm font-semibold text-(--fx-ink-2)';
export const FX_KEY_NAME_TARGET = 'api-key-name';

/** The red action's full label: "Mint Production server key". */
export function fxMintLabel(name: string): string {
  const trimmed = name.trim();
  return trimmed ? `Mint ${trimmed} key` : 'Mint key';
}

export function FxMintApiKeyDialog({
  workspaceId,
  open,
  onOpenChange,
  onMinted,
}: MintApiKeyDialogProps) {
  const { mint, minting } = useApiKeys(workspaceId);
  const byWhom = useFxUserName();
  const [name, setName] = useState('');
  const [fullKey, setFullKey] = useState<string | null>(null);
  const why = useFxActionError();
  const { clear } = why;
  useHideMainAction(open);

  // Forget everything when the dialog closes (never leave a plaintext key).
  useEffect(() => {
    if (!open) {
      setName('');
      setFullKey(null);
      clear();
    }
  }, [open, clear]);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed || minting) return;
    try {
      const result = await mint(trimmed);
      setFullKey(result.fullKey);
      onMinted();
      toast.fxDone({ what: `API key ${trimmed} minted`, byWhom });
    } catch {
      why.show("Couldn't mint the key. Try again.");
    }
  };

  const revealed = fullKey !== null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-fx-mint-dialog=""
        showCloseButton={false}
        className="max-w-lg gap-4 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)] max-sm:p-4"
      >
        <DialogTitle className="text-lg font-bold text-(--fx-ink)">
          {revealed ? 'API key created' : 'Mint API key'}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {revealed ? 'API key created' : 'Mint API key'}
        </DialogDescription>

        {!revealed ? (
          <>
            <div
              className="flex min-w-0 flex-col gap-1.5"
              data-fx-pulse-target={FX_KEY_NAME_TARGET}
            >
              <label htmlFor="fx-api-key-name" className={LABEL}>
                Key name
              </label>
              <Input
                id="fx-api-key-name"
                autoFocus
                placeholder="e.g. Production server"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && name.trim() && !minting) {
                    e.preventDefault();
                    void submit();
                  }
                }}
              />
            </div>
            <div className="mt-1 flex flex-nowrap items-start justify-end gap-2 max-sm:pb-6">
              <Button
                type="button"
                variant="fx-quiet"
                className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
                onClick={() => onOpenChange(false)}
                disabled={minting}
              >
                Cancel
              </Button>
              <div className="relative">
                <FxMainAction
                  label="Mint key"
                  fullLabel={fxMintLabel(name)}
                  working={minting}
                  blocked={
                    name.trim()
                      ? undefined
                      : {
                          reason: 'Enter a key name.',
                          pulseTarget: FX_KEY_NAME_TARGET,
                        }
                  }
                  onClick={() => void submit()}
                />
                <FxActionError message={why.message} />
              </div>
            </div>
          </>
        ) : (
          <>
            <FxSecretOnce value={fullKey} label="API key" />
            <div className="mt-1 flex justify-end">
              <FxMainAction label="Done" onClick={() => onOpenChange(false)} />
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
