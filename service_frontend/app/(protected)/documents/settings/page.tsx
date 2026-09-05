'use client';

import { useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import type { DocumentSettings, PublicSharingPolicy } from '@/types/documents';
import { documentService } from '@/services/document-service';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { formatBytes } from '@/components/platform/document-drive/lib';
import { PageHeader } from '@/components/platform/page-header';
import { SearchSelect } from '@/components/platform/search-select';

const SHARING_OPTIONS = [
  { value: 'off', label: 'Off - no public links' },
  { value: 'view', label: 'View only - public links can download' },
  { value: 'edit', label: 'Edit - public links can also upload' },
];

export default function DocumentSettingsPage() {
  const [settings, setSettings] = useState<DocumentSettings | null>(null);
  const [defaultMaxFileMb, setDefaultMaxFileMb] = useState('');
  const [storageQuotaMb, setStorageQuotaMb] = useState('');
  const [publicSharing, setPublicSharing] =
    useState<PublicSharingPolicy>('off');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    documentService.getSettings().then((s) => {
      setSettings(s);
      setDefaultMaxFileMb(String(s.defaultMaxFileMb));
      setStorageQuotaMb(
        s.storageQuotaMb != null ? String(s.storageQuotaMb) : '',
      );
      setPublicSharing(s.publicSharing);
    });
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await documentService.updateSettings({
        defaultMaxFileMb: Number(defaultMaxFileMb) || 0,
        storageQuotaMb: storageQuotaMb.trim() ? Number(storageQuotaMb) : null,
        publicSharing,
      });
      setSettings(updated);
      toast.success('Settings saved.');
    } finally {
      setSaving(false);
    }
  };

  const usagePct =
    settings && settings.storageQuotaMb
      ? Math.min(
          100,
          (settings.usedBytes / (settings.storageQuotaMb * 1024 * 1024)) * 100,
        )
      : 0;

  return (
    <RequirePermission permission="documents.configure">
      <Container width="fluid">
        <PageHeader
          title="Document settings"
          description="Storage limits, default upload caps and sharing policy."
        />
        <div className="grid max-w-2xl gap-5">
          <Card>
            <CardHeader>
              <CardTitle>Storage</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              {settings && (
                <div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Used</span>
                    <span>
                      {formatBytes(settings.usedBytes)}
                      {settings.storageQuotaMb != null
                        ? ` of ${settings.storageQuotaMb} MB`
                        : ''}
                    </span>
                  </div>
                  {settings.storageQuotaMb != null && (
                    <Progress value={usagePct} className="mt-2 h-2" />
                  )}
                </div>
              )}
              <div className="grid gap-2">
                <Label htmlFor="quota">Storage quota (MB)</Label>
                <Input
                  id="quota"
                  type="number"
                  min={0}
                  value={storageQuotaMb}
                  placeholder="Blank = unlimited"
                  onChange={(e) => setStorageQuotaMb(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="defaultmax">Default max file size (MB)</Label>
                <Input
                  id="defaultmax"
                  type="number"
                  min={1}
                  value={defaultMaxFileMb}
                  onChange={(e) => setDefaultMaxFileMb(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Applies to uploads with no document type assigned.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sharing policy</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              <Label>Public link sharing</Label>
              <SearchSelect
                options={SHARING_OPTIONS}
                value={publicSharing}
                onChange={(v) => setPublicSharing(v as PublicSharingPolicy)}
              />
              <p className="text-xs text-muted-foreground">
                Internal and specific-user links are always available. This
                ceiling caps what anonymous public links can do.
              </p>
            </CardContent>
          </Card>

          <div className="flex justify-end">
            <Button onClick={() => void save()} disabled={saving || !settings}>
              {saving ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </div>
      </Container>
    </RequirePermission>
  );
}
