'use client';

import { Fragment, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { importService } from '@/services/import-service';

/**
 * Import engine tenant settings (plan sprint-3/09 D11) — per-tenant caps
 * enforced fail-fast at upload. Blank/0 falls back to the deployment default.
 * Gated by imports.read_all (the tenant-admin import capability).
 */
function ImportSettingsForm() {
  const [maxRows, setMaxRows] = useState('');
  const [maxFileMb, setMaxFileMb] = useState('');
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    importService
      .getSettings()
      .then((s) => {
        setMaxRows(String(s.maxRows));
        setMaxFileMb(String(s.maxFileMb));
        setIsDefault(s.isDefault);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    const rows = Number(maxRows);
    const mb = Number(maxFileMb);
    if (!Number.isInteger(rows) || rows < 1 || rows > 1_000_000) {
      toast.error('Max rows: a whole number between 1 and 1,000,000.');
      return;
    }
    if (!Number.isInteger(mb) || mb < 1 || mb > 1024) {
      toast.error('Max file size: a whole number of MB between 1 and 1024.');
      return;
    }
    setSaving(true);
    try {
      const s = await importService.updateSettings(rows, mb);
      setMaxRows(String(s.maxRows));
      setMaxFileMb(String(s.maxFileMb));
      setIsDefault(s.isDefault);
      toast.success('Import limits saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Import limits</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label htmlFor="max-rows">Max rows per import</Label>
          <Input
            id="max-rows"
            type="number"
            min={1}
            max={1_000_000}
            value={maxRows}
            disabled={loading}
            onChange={(e) => setMaxRows(e.target.value)}
          />
        </div>
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label htmlFor="max-mb">Max file size (MB)</Label>
          <Input
            id="max-mb"
            type="number"
            min={1}
            max={1024}
            value={maxFileMb}
            disabled={loading}
            onChange={(e) => setMaxFileMb(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {isDefault ? 'Using the deployment defaults.' : 'Custom for this workspace.'}
          </p>
        </div>
        <div>
          <Button onClick={() => void save()} disabled={saving || loading}>
            Save
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ImportSettingsPage() {
  return (
    <RequirePermission permission="imports.read_all">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text="Import settings" />
              <ToolbarDescription>
                Caps applied to every bulk import in this workspace.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ImportSettingsForm />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
