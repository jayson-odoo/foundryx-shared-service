'use client';

/**
 * Share dialog (plan sprint-3/05, Google-Drive model). A target has ONE stable
 * link; this dialog ensures it on open and edits it in place:
 *   - "People with access" - add named users, each with their own View/Edit role.
 *   - "General access" - Restricted | Anyone in the workspace | Anyone with the
 *     link, with a role; the Public option is hidden when the tenant ceiling is
 *     off, and Editor is disabled for Public when ceiling=view or the user lacks
 *     documents.manage (foolproof - can't configure a guaranteed rejection).
 *   - Advanced - expiry, password, and (public-edit) upload caps.
 * The copyable link never changes when access is edited (Google semantics).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Copy, Globe, Link2, Lock, Loader2, Users, X } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { documentService } from '@/services/document-service';
import type {
  PublicSharingPolicy,
  ShareCapability,
  ShareGeneralAccess,
  ShareRow,
  ShareUpdatePayload,
  ShareUser,
} from '@/types/documents';

export interface ShareTarget {
  kind: 'file' | 'folder';
  id: string;
  name: string;
}

const ROLE_OPTIONS = [
  { value: 'view', label: 'Viewer' },
  { value: 'edit', label: 'Editor' },
];

export function ShareDialog({
  target,
  ceiling,
  canManage,
  onClose,
}: {
  target: ShareTarget | null;
  ceiling: PublicSharingPolicy;
  canManage: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog open={target !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-lg">
        {target && <Body target={target} ceiling={ceiling} canManage={canManage} />}
      </DialogContent>
    </Dialog>
  );
}

function Body({
  target,
  ceiling,
  canManage,
}: {
  target: ShareTarget;
  ceiling: PublicSharingPolicy;
  canManage: boolean;
}) {
  const [share, setShare] = useState<ShareRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userOptions, setUserOptions] = useState<ShareUser[]>([]);
  const { isCopied, copyToClipboard } = useCopyToClipboard();

  const publicOff = ceiling === 'off';
  const publicEditLocked = ceiling === 'view' || !canManage;

  useEffect(() => {
    documentService
      .ensureShare(target.kind, target.id)
      .then(setShare)
      .catch(() => setError('Could not open sharing for this item.'));
  }, [target.kind, target.id]);

  useEffect(() => {
    documentService.listShareUsers().then(setUserOptions).catch(() => setUserOptions([]));
  }, []);

  const patch = useCallback(
    async (body: ShareUpdatePayload) => {
      if (!share) return;
      setBusy(true);
      setError(null);
      try {
        setShare(await documentService.updateShare(share.id, body));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not update sharing.');
      } finally {
        setBusy(false);
      }
    },
    [share],
  );

  const shareUrl = useMemo(() => {
    if (!share) return '';
    return typeof window !== 'undefined'
      ? `${window.location.origin}/public/documents/${share.token}`
      : share.url;
  }, [share]);

  if (error && !share) {
    return <p className="py-6 text-center text-sm text-destructive">{error}</p>;
  }
  if (!share) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
      </div>
    );
  }

  const accessOptions = [
    { value: 'restricted', label: 'Restricted - only people added below' },
    { value: 'workspace', label: 'Anyone in the workspace' },
    ...(publicOff ? [] : [{ value: 'public', label: 'Anyone with the link' }]),
  ];

  const peopleIds = new Set(share.people.map((p) => p.id));
  const addable = userOptions.filter((u) => !peopleIds.has(u.id));

  const setPeople = (people: ShareUser[]) =>
    patch({ people: people.map((p) => ({ userId: p.id, capability: (p.capability ?? 'view') as ShareCapability })) });

  const addPerson = (userId: string) => {
    const u = userOptions.find((x) => x.id === userId);
    if (!u) return;
    void setPeople([...share.people, { ...u, capability: 'view' }]);
  };
  const removePerson = (userId: string) =>
    void setPeople(share.people.filter((p) => p.id !== userId));
  const setPersonRole = (userId: string, capability: ShareCapability) =>
    void setPeople(share.people.map((p) => (p.id === userId ? { ...p, capability } : p)));

  const generalEditDisabled =
    share.generalAccess === 'public' && publicEditLocked;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-heading text-lg font-semibold">Share</h2>
        <p className="mt-0.5 flex items-center gap-1.5 text-sm text-muted-foreground">
          <Link2 className="size-4 shrink-0" />
          <ClampedText
            className="min-w-0"
            text={`${target.kind === 'folder' ? 'Folder' : 'File'} · ${target.name}`}
          />
        </p>
      </div>

      {/* People with access */}
      <div className="grid gap-2">
        <Label className="flex items-center gap-1.5">
          <Users className="size-4" /> People with access
        </Label>
        <SearchSelect
          options={addable.map((u) => ({ value: u.id, label: u.name || u.email || u.id }))}
          value={null}
          onChange={addPerson}
          placeholder="Add people…"
          ariaLabel="Add people"
        />
        {share.people.length > 0 && (
          <ul className="grid gap-1.5">
            {share.people.map((p) => (
              <li key={p.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5" data-testid="share-person">
                <span className="min-w-0 flex-1 truncate text-sm">{p.name || p.email || p.id}</span>
                <div className="w-24 shrink-0">
                  <SearchSelect
                    options={ROLE_OPTIONS}
                    value={p.capability ?? 'view'}
                    onChange={(v) => setPersonRole(p.id, v as ShareCapability)}
                    ariaLabel="Person role"
                  />
                </div>
                <button
                  type="button"
                  className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted"
                  onClick={() => removePerson(p.id)}
                  aria-label="Remove person"
                >
                  <X className="size-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* General access */}
      <div className="grid gap-2 border-t pt-3">
        <Label className="flex items-center gap-1.5">
          {share.generalAccess === 'public' ? <Globe className="size-4" /> : <Lock className="size-4" />}
          General access
        </Label>
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1">
            <SearchSelect
              options={accessOptions}
              value={share.generalAccess}
              onChange={(v) => patch({ generalAccess: v as ShareGeneralAccess })}
              ariaLabel="General access"
            />
          </div>
          {share.generalAccess !== 'restricted' && (
            <div className="w-28 shrink-0">
              <SearchSelect
                options={ROLE_OPTIONS.map((o) => ({
                  ...o,
                  label: generalEditDisabled && o.value === 'edit' ? 'Editor (locked)' : o.label,
                }))}
                value={share.capability}
                onChange={(v) => {
                  if (generalEditDisabled && v === 'edit') return;
                  patch({ capability: v as ShareCapability });
                }}
                ariaLabel="General role"
              />
            </div>
          )}
        </div>
        {publicOff && (
          <p className="text-xs text-muted-foreground">
            Public links are turned off for this workspace - enable them in Document settings.
          </p>
        )}
        {share.generalAccess === 'public' && publicEditLocked && (
          <p className="text-xs text-warning">
            {ceiling === 'view' ? 'Public links are view-only here.' : 'Public edit requires the Manage documents permission.'}
          </p>
        )}
      </div>

      {/* Advanced */}
      <AdvancedOptions share={share} patch={patch} />

      {error && (
        <Alert variant="destructive" appearance="light">
          <AlertIcon><Lock /></AlertIcon>
          <AlertTitle>{error}</AlertTitle>
        </Alert>
      )}

      {/* Stable link */}
      <div className="flex items-center gap-2 border-t pt-3">
        <Input readOnly value={shareUrl} className="font-mono text-xs" data-testid="share-url" />
        <Button size="sm" onClick={() => copyToClipboard(shareUrl)} disabled={busy} data-testid="copy-link">
          {isCopied ? <Check className="size-4" /> : <Copy className="size-4" />}
          {isCopied ? 'Copied' : 'Copy link'}
        </Button>
      </div>
    </div>
  );
}

function AdvancedOptions({
  share,
  patch,
}: {
  share: ShareRow;
  patch: (body: ShareUpdatePayload) => Promise<void>;
}) {
  const [expiry, setExpiry] = useState(share.expiresAt ? share.expiresAt.slice(0, 10) : '');
  const [password, setPassword] = useState('');
  const todayStr = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const isPublicEdit = share.generalAccess === 'public' && share.capability === 'edit';

  return (
    <div className="grid gap-3 rounded-md border bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="share-expiry" className="text-sm font-normal">Expiry date</Label>
        <Switch
          id="share-expiry"
          checked={share.expiresAt !== null}
          onCheckedChange={(on) => {
            if (!on) {
              setExpiry('');
              void patch({ expiresAt: null });
            } else if (expiry) {
              void patch({ expiresAt: new Date(`${expiry}T23:59:59Z`).toISOString() });
            }
          }}
        />
      </div>
      {share.expiresAt !== null && (
        <Input
          type="date"
          min={todayStr}
          value={expiry}
          aria-label="Expiry date"
          onChange={(e) => {
            setExpiry(e.target.value);
            if (e.target.value >= todayStr) {
              void patch({ expiresAt: new Date(`${e.target.value}T23:59:59Z`).toISOString() });
            }
          }}
        />
      )}

      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="share-pw" className="flex items-center gap-1.5 text-sm font-normal">
          <Lock className="size-3.5" /> Password
        </Label>
        <Switch
          id="share-pw"
          checked={share.hasPassword}
          onCheckedChange={(on) => {
            if (!on) {
              setPassword('');
              void patch({ password: null });
            }
          }}
        />
      </div>
      {(share.hasPassword || password) && !share.hasPassword && (
        <div className="flex items-center gap-2">
          <Input
            type="text"
            value={password}
            placeholder="Set a password"
            aria-label="Share password"
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button size="sm" disabled={!password.trim()} onClick={() => void patch({ password })}>
            Set
          </Button>
        </div>
      )}
      {share.hasPassword && (
        <p className="text-xs text-muted-foreground">Password is set. Toggle off to remove it.</p>
      )}

      {isPublicEdit && (
        <div className="grid grid-cols-2 gap-2">
          <div className="grid gap-1">
            <Label className="text-xs font-normal text-muted-foreground">Max uploads</Label>
            <Input
              type="number"
              min={1}
              defaultValue={share.maxUploads ?? ''}
              placeholder="50"
              onBlur={(e) => void patch({ maxUploads: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
          <div className="grid gap-1">
            <Label className="text-xs font-normal text-muted-foreground">Max total MB</Label>
            <Input
              type="number"
              min={1}
              defaultValue={share.maxTotalMb ?? ''}
              placeholder="200"
              onBlur={(e) => void patch({ maxTotalMb: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
        </div>
      )}
    </div>
  );
}
