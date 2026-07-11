'use client';

import { useState } from 'react';
import { KeyRound, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { useEmbedConfig } from '@/hooks/use-embed-config';
import { CopyField } from './copy-field';
import { OriginsEditor } from './origins-editor';
import { SnippetCard } from './snippet-card';

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <Skeleton className="h-40 w-full rounded-lg" />
      <Skeleton className="h-40 w-full rounded-lg" />
    </div>
  );
}

/**
 * Tenant-level embed-access admin. Provisions the `omnichannel_shared`
 * connection, rotates the write-only signing secret, edits the allowed parent
 * origins, and builds the iframe snippet. The secret is shown exactly once at
 * rotation.
 */
export function EmbedAccessPanel() {
  const { config, loading, error, enable, rotateSecret, setOrigins, reload } = useEmbedConfig();
  const [enabling, setEnabling] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);

  if (loading && !config) return <LoadingSkeleton />;

  if (error && !config) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 py-6">
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button variant="outline" onClick={() => void reload()}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!config) return null;

  const onEnable = async () => {
    setEnabling(true);
    try {
      await enable();
      toast.success('Embed access enabled.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not enable embed access.');
    } finally {
      setEnabling(false);
    }
  };

  const onRotate = async () => {
    setRotating(true);
    try {
      const secret = await rotateSecret();
      setRevealedSecret(secret);
      setConfirmRotate(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not generate a secret.');
    } finally {
      setRotating(false);
    }
  };

  // Empty state — not yet provisioned.
  if (!config.connectionId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-4 py-8">
          <div className="flex items-center gap-2 text-muted-foreground">
            <ShieldCheck className="size-5" />
            <span className="text-sm">
              Embed our conversation UI as a token-authed iframe on your own pages.
            </span>
          </div>
          <Button onClick={() => void onEnable()} disabled={enabling}>
            {enabling ? 'Enabling…' : 'Enable embed access'}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Connection id */}
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Connection id</CardTitle>
            <CardDescription>
              The non-secret identifier — the iframe&apos;s <code>?c=</code> and the assertion
              issuer.
            </CardDescription>
          </CardHeading>
        </CardHeader>
        <CardContent>
          <CopyField value={config.connectionId} ariaLabel="connection id" />
        </CardContent>
      </Card>

      {/* Embed secret */}
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Embed secret</CardTitle>
            <CardDescription>The signing key for embed assertions.</CardDescription>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" />
            {config.hasSecret ? (
              <Badge variant="success" appearance="outline">
                Set
              </Badge>
            ) : (
              <Badge variant="secondary" appearance="outline">
                Not set
              </Badge>
            )}
          </div>

          {revealedSecret && (
            <div className="flex flex-col gap-2 rounded-md border border-amber-500/40 bg-amber-50 p-3 dark:bg-amber-950/20">
              <Label>New secret — copy it now, it won&apos;t be shown again</Label>
              <CopyField value={revealedSecret} ariaLabel="embed secret" />
            </div>
          )}

          <div>
            <Button
              variant={config.hasSecret ? 'outline' : 'primary'}
              onClick={() => setConfirmRotate(true)}
            >
              {config.hasSecret ? 'Rotate secret' : 'Generate secret'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Allowed origins */}
      <OriginsEditor origins={config.allowedOrigins} onSave={setOrigins} />

      {/* Iframe snippet */}
      <SnippetCard
        host={config.host}
        connectionId={config.connectionId}
        workspaces={config.workspaces}
      />

      <AlertDialog open={confirmRotate} onOpenChange={setConfirmRotate}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {config.hasSecret ? 'Rotate the embed secret?' : 'Generate an embed secret?'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {config.hasSecret
                ? 'A new secret is generated and shown once. Every outstanding assertion signed with the old secret stops working immediately — update your consumer backend with the new value.'
                : 'A new secret is generated and shown once. Sign your embed assertions with it on your consumer backend.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={rotating}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={(e) => { e.preventDefault(); void onRotate(); }} disabled={rotating}>
              {rotating ? 'Generating…' : config.hasSecret ? 'Rotate' : 'Generate'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
