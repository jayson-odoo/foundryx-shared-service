'use client';

import type { UseFormReturn } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { SearchSelect } from '@/components/platform/search-select';
import { DynamicContentField, type DynamicContentGroup } from '@/components/platform/workflow-canvas/dynamic-content-picker';
import { catalogEntry } from '@/lib/workflow-catalog';
import { useDatetime } from '@/hooks/use-datetime';
import type { Workflow, WorkflowDefinition, WorkflowManualInput } from '@/types/workflows';
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
  definition: WorkflowDefinition;
  onDefinitionChange: (definition: WorkflowDefinition) => void;
}

export function WorkflowSettingsFields({
  form,
  editing,
  workflow,
  canManage,
  busy,
  onSetActive,
  definition,
  onDefinitionChange,
}: WorkflowSettingsFieldsProps) {
  const values = form.watch();
  const { formatDateTime } = useDatetime();
  const execution = definition.execution ?? { mode: 'parallel' as const, correlationKey: '' };
  const trigger = definition.nodes.find((node) => node.kind === 'trigger');
  const triggerEntry = trigger ? catalogEntry(trigger.type) : undefined;
  const correlationGroups: DynamicContentGroup[] = trigger
    ? [{
        sourceLabel: triggerEntry?.label ?? 'Trigger',
        items: [
          ...(triggerEntry?.outputs ?? []),
          ...((Array.isArray(trigger.config.inputs) ? trigger.config.inputs : []) as WorkflowManualInput[]).map((input) => ({ key: `trigger.input.${input.key}`, label: input.label || input.key })),
        ],
      }]
    : [];
  const updateExecution = (patch: Partial<typeof execution>) =>
    onDefinitionChange({
      ...definition,
      schemaVersion: Math.max(definition.schemaVersion, 2),
      execution: { ...execution, ...patch },
    });

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
                : 'Disabled - triggers will not fire it.'}
            </span>
          </div>
        </Row>
      )}

      <Row label="Name" required>
        {editing ? (
          <Input
            aria-label="Workflow name"
            value={values.name}
            disabled={busy}
            onChange={(e) => form.setValue('name', e.target.value, { shouldDirty: true })}
          />
        ) : (
          <span className="text-sm font-medium">{values.name || '-'}</span>
        )}
      </Row>

      <Row label="Description">
        {editing ? (
          <Textarea
            aria-label="Workflow description"
            rows={3}
            value={values.description}
            disabled={busy}
            onChange={(e) => form.setValue('description', e.target.value, { shouldDirty: true })}
          />
        ) : (
          <span className="text-sm text-muted-foreground">{values.description || '-'}</span>
        )}
      </Row>

      <Row label="Execution mode">
        {editing ? (
          <SearchSelect
            options={[
              { value: 'parallel', label: 'Parallel' },
              { value: 'serialized', label: 'Serialized by key' },
            ]}
            value={execution.mode}
            onChange={(mode) => updateExecution({ mode: mode as 'parallel' | 'serialized' })}
            ariaLabel="Execution mode"
            searchPlaceholder="Search execution modes…"
          />
        ) : (
          <span className="text-sm font-medium" data-testid="execution-mode-value">
            {execution.mode === 'serialized' ? 'Serialized by key' : 'Parallel'}
          </span>
        )}
      </Row>

      {execution.mode === 'serialized' && (
        <Row label="Correlation key" required>
          {editing ? (
            <DynamicContentField
              value={execution.correlationKey}
              onChange={(correlationKey) => updateExecution({ correlationKey })}
              groups={correlationGroups}
              placeholder="{{ trigger.conversationId }}"
              aria-label="Correlation key"
            />
          ) : (
            <span className="font-mono text-sm" data-testid="correlation-key-value">
              {execution.correlationKey || '-'}
            </span>
          )}
        </Row>
      )}

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
