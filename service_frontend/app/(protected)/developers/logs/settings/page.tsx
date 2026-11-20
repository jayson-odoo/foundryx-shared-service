'use client';

import { useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { useIntegrationLogSettings } from '@/hooks/use-integration-log-settings';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';

/**
 * Developer Logs retention settings (sprint-4/12 Slice 3, AC-DLC-21/23) - the
 * beat pruner deletes integration-activity rows older than this window (left at
 * the deployment default until overridden here). Gated integration_logs.manage.
 * Reuses the /settings/workflows page shape.
 */
function LogRetentionForm() {
  const { settings, isLoading, isSaving, save } = useIntegrationLogSettings();
  const [days, setDays] = useState('');

  useEffect(() => {
    if (settings) setDays(String(settings.retentionDays));
  }, [settings]);

  const onSave = async () => {
    const n = Number(days);
    if (!Number.isInteger(n) || n < 1 || n > 3650) {
      toast.error('Enter a whole number of days between 1 and 3650.');
      return;
    }
    try {
      await save(n);
      toast.success('Log retention saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Log retention</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label htmlFor="log-retention-days">
            Keep developer logs for (days)
          </Label>
          <Input
            id="log-retention-days"
            type="number"
            min={1}
            max={3650}
            value={days}
            disabled={isLoading}
            onChange={(e) => setDays(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {settings?.isDefault
              ? 'Using the deployment default.'
              : 'Custom for this workspace.'}
          </p>
        </div>
        <div>
          <Button
            onClick={() => void onSave()}
            disabled={isSaving || isLoading}
          >
            Save log settings
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function DeveloperLogSettingsPage() {
  return (
    <RequirePermission permission="integration_logs.manage">
      <Container width="fluid">
        <PageHeader description="How long integration activity is kept before it is automatically pruned." />
        <LogRetentionForm />
      </Container>
    </RequirePermission>
  );
}
