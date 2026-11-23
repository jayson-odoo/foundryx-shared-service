'use client';

/**
 * Embed access with the Foundryx UIUX switch on (slice W2-WS, gap audit
 * "Secrets shown once"). Same steps and the same requests as with the switch
 * off (`useEmbedConfig`: enable, rotate secret, save origins); what changes:
 * - Not enabled yet: "Enable embed access" is the page's red action.
 * - The signing secret is write-only: once set it reads "Saved" with
 *   Replace, never a value. The API reports only whether one is set, so
 *   there is no "ending a91c" to show.
 * - Replace (or Generate) asks first with the playbook confirm; rotating says
 *   what stops working and needs the press and hold.
 * - The new secret shows in full only in the dialog that made it, with Copy
 *   and one warning line; Done closes it and the secret is forgotten.
 */
import { useMemo, useRef, useState } from 'react';
import { Code2, Globe, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import { useEmbedConfig } from '@/hooks/use-embed-config';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { FxConfirmDialog } from '@/components/fx/actions/confirm-dialog';
import { FxMainAction } from '@/components/fx/actions/main-action';
import {
  useHideMainAction,
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxSecretOnce } from '@/components/fx/fields';
import { FX_FIELD_BOX } from '@/components/fx/fields/classes';
import { useFxUserName } from '../workspaces/components/use-fx-user-name';
import { CopyField } from './copy-field';
import { LoadingSkeleton, SettingRow } from './embed-access-panel';
import { OriginsEditor } from './origins-editor';
import { SnippetCard } from './snippet-card';

/** The new secret, shown once. Closing forgets it. */
function FxNewSecretDialog({
  secret,
  onDone,
}: {
  secret: string | null;
  onDone: () => void;
}) {
  const open = secret !== null;
  useHideMainAction(open);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onDone()}>
      <DialogContent
        data-fx-secret-dialog=""
        showCloseButton={false}
        className="max-w-lg gap-4 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)] max-sm:p-4"
      >
        <DialogTitle className="text-lg font-bold text-(--fx-ink)">
          New embed secret
        </DialogTitle>
        <DialogDescription className="sr-only">
          New embed secret
        </DialogDescription>
        {secret !== null && (
          <FxSecretOnce value={secret} label="Embed secret" />
        )}
        <div className="mt-1 flex justify-end">
          <FxMainAction label="Done" onClick={onDone} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function FxEmbedAccessPanel() {
  const { config, loading, error, enable, rotateSecret, setOrigins, reload } =
    useEmbedConfig();
  const byWhom = useFxUserName();
  const [enabling, setEnabling] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);

  const onEnable = async () => {
    setEnabling(true);
    try {
      await enable();
      toast.fxDone({ what: 'Embed access enabled', byWhom });
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Couldn't enable embed access.",
      );
    } finally {
      setEnabling(false);
    }
  };

  const onRotate = async () => {
    if (rotating) return;
    setConfirmRotate(false);
    setRotating(true);
    try {
      const secret = await rotateSecret();
      setRevealedSecret(secret);
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Couldn't make a new secret.",
      );
    } finally {
      setRotating(false);
    }
  };

  const onEnableRef = useRef(onEnable);
  onEnableRef.current = onEnable;
  const notEnabled = Boolean(config && !config.connectionId);
  const enableAction = useMemo<FxMainActionSpec | null>(
    () =>
      notEnabled
        ? {
            id: 'enable-embed',
            label: 'Enable embed access',
            onClick: () => void onEnableRef.current(),
            working: enabling,
          }
        : null,
    [notEnabled, enabling],
  );
  useRegisterMainAction(enableAction);

  if (loading && !config) return <LoadingSkeleton />;

  if (error && !config) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 py-6">
          <p className="text-sm text-(--fx-ink-2)">{error}</p>
          <Button variant="outline" onClick={() => void reload()}>
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!config) return null;

  if (!config.connectionId) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-8 text-(--fx-ink-2)">
          <ShieldCheck aria-hidden="true" className="size-5 shrink-0" />
          <span className="text-sm">Embed access is off.</span>
        </CardContent>
      </Card>
    );
  }

  const hasSecret = config.hasSecret;

  return (
    <>
      <Tabs defaultValue="setup">
        <TabsList variant="line" className="max-w-full overflow-x-auto">
          <TabsTrigger value="setup">
            <SlidersHorizontal />
            Setup
          </TabsTrigger>
          <TabsTrigger value="origins">
            <Globe />
            Allowed origins
          </TabsTrigger>
          <TabsTrigger value="snippet">
            <Code2 />
            Snippet
          </TabsTrigger>
        </TabsList>

        <TabsContent value="setup" className="pt-2">
          <Card>
            <CardContent className="divide-y py-2">
              <SettingRow
                label="Connection id"
                description="The non-secret identifier - the iframe's ?c= and the assertion issuer."
              >
                <CopyField
                  value={config.connectionId}
                  ariaLabel="connection id"
                />
              </SettingRow>
              <SettingRow
                label="Embed secret"
                description="The signing key for embed assertions. Shared across your workspaces; shown once when rotated."
              >
                <div
                  data-fx-embed-secret=""
                  className={cn(
                    FX_FIELD_BOX,
                    'h-8.5 justify-between gap-2 ps-3 pe-1 text-[0.8125rem]',
                  )}
                >
                  <span className="text-(--fx-ink-2)">
                    {hasSecret ? 'Saved' : 'No secret set'}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={rotating}
                    onClick={() => setConfirmRotate(true)}
                  >
                    {hasSecret ? 'Replace' : 'Generate secret'}
                  </Button>
                </div>
              </SettingRow>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="origins" className="pt-2">
          <OriginsEditor origins={config.allowedOrigins} onSave={setOrigins} />
        </TabsContent>

        <TabsContent value="snippet" className="pt-2">
          <SnippetCard
            host={config.host}
            connectionId={config.connectionId}
            workspaces={config.workspaces}
          />
        </TabsContent>
      </Tabs>

      <FxConfirmDialog
        open={confirmRotate}
        title={
          hasSecret ? 'Rotate the embed secret?' : 'Generate an embed secret?'
        }
        line={
          hasSecret
            ? 'Assertions signed with the old secret will fail at once. The new one is shown once.'
            : 'The new secret is shown once.'
        }
        keepLabel={hasSecret ? 'Keep current secret' : 'Keep without a secret'}
        actionLabel={hasSecret ? 'Rotate secret' : 'Generate secret'}
        destructive={hasSecret}
        hold={hasSecret ? undefined : false}
        onKeep={() => setConfirmRotate(false)}
        onConfirm={() => void onRotate()}
      />
      <FxNewSecretDialog
        secret={revealedSecret}
        onDone={() => setRevealedSecret(null)}
      />
    </>
  );
}
