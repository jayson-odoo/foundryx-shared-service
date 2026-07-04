'use client';

import type { UseFormReturn } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useDatetime } from '@/hooks/use-datetime';
import type { Workflow } from '@/types/workflows';
import type { WorkflowFormValues } from './use-workflow-form';

function Row({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">
        {label}
        {required && <span className="text-destructive"> *</span>}
      </Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export interface WorkflowSettingsFieldsProps {
  form: UseFormReturn<WorkflowFormValues>;
  editing: boolean;
  workflow: Workflow | null;
  canManage: boolean;
  busy: boolean;
  onSetActive: (active: boolean) => void;
}

export function WorkflowSettingsFields({
  form,
  editing,
  workflow,
  canManage,
  busy,
  onSetActive,
}: WorkflowSettingsFieldsProps) {
  const values = form.watch();
  const { formatDateTime } = useDatetime();

  return (
    <div className="flex flex-col gap-5 py-2">
      {workflow && (
        <Row label="Active">
          <div className="flex items-center gap-2.5">
            <Switch
              checked={workflow.isActive}
              disabled={!canManage || busy}
              onCheckedChange={onSetActive}
              data-testid="workflow-active-switch"
            />
            <span className="text-sm text-muted-foreground">
              {workflow.isActive
                ? 'Triggers can fire this workflow (when published).'
                : 'Disabled — triggers will not fire it.'}
            </span>
          </div>
        </Row>
      )}

      <Row label="Name" required>
        {editing ? (
          <Input
            aria-label="Workflow name"
            value={values.name}
            onChange={(e) => form.setValue('name', e.target.value, { shouldDirty: true })}
          />
        ) : (
          <span className="text-sm font-medium">{values.name || '—'}</span>
        )}
      </Row>

      <Row label="Description">
        {editing ? (
          <Textarea
            aria-label="Workflow description"
            rows={3}
            value={values.description}
            onChange={(e) => form.setValue('description', e.target.value, { shouldDirty: true })}
          />
        ) : (
          <span className="text-sm text-muted-foreground">{values.description || '—'}</span>
        )}
      </Row>

      {workflow && (
        <>
          <Row label="Created by">
            <span className="text-sm text-muted-foreground">
              {workflow.createdByName} · {formatDateTime(workflow.createdAt)}
            </span>
          </Row>

          <Row label="Current version">
            {workflow.currentVersion ? (
              <span className="text-sm text-foreground" data-testid="current-version">
                v{workflow.currentVersion.versionNumber}
                <span className="ml-1.5 text-xs text-muted-foreground">
                  {workflow.currentVersion.publishedByName} ·{' '}
                  {formatDateTime(workflow.currentVersion.publishedAt)}
                </span>
              </span>
            ) : (
              <span className="text-sm text-muted-foreground">Not published yet.</span>
            )}
            <p className="mt-1 text-xs text-muted-foreground">Full history is in the Versions tab.</p>
          </Row>
        </>
      )}
    </div>
  );
}
