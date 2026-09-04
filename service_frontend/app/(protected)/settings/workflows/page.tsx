'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { workflowService } from '@/services/workflow-service';
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
 * Workflow engine tenant settings (plan sprint-2/10) - run retention. The
 * scheduler prunes a tenant's workflow runs older than this window; left at the
 * deployment default until overridden here. Gated by workflows.manage.
 */
function WorkflowSettingsForm() {
  const [days, setDays] = useState('');
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    workflowService
      .getSettings()
      .then((s) => {
        setDays(String(s.runRetentionDays));
        setIsDefault(s.isDefault);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    const n = Number(days);
    if (!Number.isInteger(n) || n < 1 || n > 3650) {
      toast.error('Enter a whole number of days between 1 and 3650.');
      return;
    }
    setSaving(true);
    try {
      const s = await workflowService.updateSettings(n);
      setDays(String(s.runRetentionDays));
      setIsDefault(s.isDefault);
      toast.success('Workflow settings saved.');
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
          <CardTitle>Run retention</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label htmlFor="run-retention-days">
            Keep run history for (days)
          </Label>
          <Input
            id="run-retention-days"
            type="number"
            min={1}
            max={3650}
            value={days}
            disabled={loading}
            onChange={(e) => setDays(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {isDefault
              ? 'Using the deployment default.'
              : 'Custom for this workspace.'}
          </p>
        </div>
        <div>
          <Button onClick={() => void save()} disabled={saving || loading}>
            Save workflow settings
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function WorkflowSettingsPage() {
  return (
    <RequirePermission permission="workflows.manage">
      <Container width="fluid">
        <PageHeader description="Run retention and other workflow engine settings for this workspace." />
        <WorkflowSettingsForm />
      </Container>
    </RequirePermission>
  );
}
