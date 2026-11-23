'use client';

/**
 * Document settings under the Foundryx UIUX switch (slice W3-DOCS): the same
 * fields and the same save body (`documentSettingsBody`); "Save settings" is
 * the page's red action ("Save document settings" in full) instead of a
 * button under the cards, and a save says what and who. No Undo: the API
 * keeps no earlier settings to go back to.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from '@/lib/toast';
import type { DocumentSettings, PublicSharingPolicy } from '@/types/documents';
import { documentService } from '@/services/document-service';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { formatBytes } from '@/components/platform/document-drive/lib';
import { PageHeader } from '@/components/platform/page-header';
import { SearchSelect } from '@/components/platform/search-select';
import { FX_FIELD_LABEL } from '@/components/fx/fields';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { useFxActorName } from '@/components/platform/document-drive/fx-drive-words';

const SHARING_OPTIONS = [
  { value: 'off', label: 'Off - no public links' },
  { value: 'view', label: 'View only - public links can download' },
  { value: 'edit', label: 'Edit - public links can also upload' },
];

/** The save body, built exactly as today's page builds it. */
export function documentSettingsBody(
  defaultMaxFileMb: string,
  storageQuotaMb: string,
  publicSharing: PublicSharingPolicy,
) {
  return {
    defaultMaxFileMb: Number(defaultMaxFileMb) || 0,
    storageQuotaMb: storageQuotaMb.trim() ? Number(storageQuotaMb) : null,
    publicSharing,
  };
}

export function FxDocumentSettings() {
  const byWhom = useFxActorName();
  const [settings, setSettings] = useState<DocumentSettings | null>(null);
  const [defaultMaxFileMb, setDefaultMaxFileMb] = useState('');
  const [storageQuotaMb, setStorageQuotaMb] = useState('');
  const [publicSharing, setPublicSharing] = useState<PublicSharingPolicy>('off');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    documentService.getSettings().then((s) => {
      setSettings(s);
      setDefaultMaxFileMb(String(s.defaultMaxFileMb));
      setStorageQuotaMb(s.storageQuotaMb != null ? String(s.storageQuotaMb) : '');
      setPublicSharing(s.publicSharing);
    });
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const updated = await documentService.updateSettings(
        documentSettingsBody(defaultMaxFileMb, storageQuotaMb, publicSharing),
      );
      setSettings(updated);
      toast.fxDone({ what: 'Document settings saved', byWhom });
    } finally {
      setSaving(false);
    }
  }, [defaultMaxFileMb, storageQuotaMb, publicSharing, byWhom]);

  const main = useMemo<FxMainActionSpec>(
    () => ({
      id: 'save',
      label: 'Save settings',
      fullLabel: 'Save document settings',
      onClick: () => {
        if (!saving && settings) void save();
      },
      working: saving,
      blocked: settings ? undefined : { reason: 'Loading the settings.' },
    }),
    [save, saving, settings],
  );
  useRegisterMainAction(main);

  const usagePct =
    settings && settings.storageQuotaMb
      ? Math.min(100, (settings.usedBytes / (settings.storageQuotaMb * 1024 * 1024)) * 100)
      : 0;

  return (
    <RequirePermission permission="documents.configure">
      <Container width="fluid">
        <PageHeader title="Document settings" description="Storage limits, default upload caps and sharing policy." />
        <form
          className="grid max-w-2xl gap-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (!saving && settings) void save();
          }}
        >
          <Card>
            <CardHeader>
              <CardTitle>Storage</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              {settings && (
                <div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-(--fx-ink-2)">Used</span>
                    <span className="tabular-nums">
                      {formatBytes(settings.usedBytes)}
                      {settings.storageQuotaMb != null ? ` of ${settings.storageQuotaMb} MB` : ''}
                    </span>
                  </div>
                  {settings.storageQuotaMb != null && <Progress value={usagePct} className="mt-2 h-2" />}
                </div>
              )}
              <div className="grid gap-2">
                <Label htmlFor="quota" className={FX_FIELD_LABEL}>
                  Storage quota (MB)
                </Label>
                <Input
                  id="quota"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  value={storageQuotaMb}
                  placeholder="Unlimited"
                  onChange={(e) => setStorageQuotaMb(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="defaultmax" className={FX_FIELD_LABEL}>
                  Default max file size (MB)
                </Label>
                <Input
                  id="defaultmax"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  value={defaultMaxFileMb}
                  onChange={(e) => setDefaultMaxFileMb(e.target.value)}
                />
                <p className="text-sm text-(--fx-ink-2)">For uploads with no document type.</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sharing policy</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              <Label className={FX_FIELD_LABEL}>Public link sharing</Label>
              <SearchSelect
                options={SHARING_OPTIONS}
                value={publicSharing}
                onChange={(v) => setPublicSharing(v as PublicSharingPolicy)}
                ariaLabel="Public link sharing"
              />
              <p className="text-sm text-(--fx-ink-2)">
                The most an anonymous public link can do. Internal and named-people links are always on.
              </p>
            </CardContent>
          </Card>
        </form>
      </Container>
    </RequirePermission>
  );
}
