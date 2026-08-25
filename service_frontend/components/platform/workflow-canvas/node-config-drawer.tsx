'use client';

/**
 * Right-side node config drawer (plan sprint-2/08 D15, extended in 09). Renders
 * the selected node's fields from its catalog entry: mergeable text → the n8n
 * dynamic-content picker, `template`/`select` → a Select, `inputs` → the
 * manual-input editor, and the slice-09 field types - `entity`/`status`/`field`
 * pickers (resolved from the workflow metadata + the node's own `entityType`),
 * `cron` → the structured cron builder, `assignments` → the field-set editor.
 * IF nodes render a `<RuleBuilder>` over the upstream run-context facts.
 * Read-only unless the form's Edit toggle is on.
 */
import { useState } from 'react';
import { Eye, Maximize2, Play, Plus, Trash2, TriangleAlert } from 'lucide-react';
import { TemplateContentEditor } from '@/components/platform/template-preview/template-content-editor';
import { templateEngineService } from '@/services/template-service';
import { isCanvasDoc, type TemplateDocument } from '@/types/templates';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { RuleBuilder } from '@/components/platform/rule-builder';
import { ACTION_CATALOG, TRIGGER_CATALOG, catalogEntry } from '@/lib/workflow-catalog';
import { nodeDisplayName } from '@/lib/workflow-doc';
import { cn } from '@/lib/utils';
import type { RuleFact, RuleFactType, RuleGroup } from '@/types/rules';
import type {
  NodeFieldDef,
  WorkflowDefinition,
  WorkflowEntityField,
  WorkflowFieldAssignment,
  WorkflowFormOption,
  WorkflowManualInput,
  WorkflowMetadata,
  WorkflowNode,
  WorkflowNodeConfig,
  WorkflowRunNode,
  WorkflowTriggerableEntity,
} from '@/types/workflows';
import { CronBuilder } from './cron-builder';
import { DynamicContentField, type DynamicContentGroup } from './dynamic-content-picker';

export interface TemplateOption {
  value: string;
  label: string;
}

export interface NodeConfigDrawerProps {
  node: WorkflowNode | null;
  doc: WorkflowDefinition;
  editing: boolean;
  templateOptions: TemplateOption[];
  /** Triggerable entities + their fields/statuses (D6). */
  metadata: WorkflowMetadata;
  onConfigChange: (nodeId: string, patch: WorkflowNodeConfig) => void;
  onDelete: (nodeId: string) => void;
  /** Quick-replace the node's catalog type (change trigger / replace action). */
  onReplaceNode?: (nodeId: string, newType: string) => void;
  /** Hide the delete control (e.g. the debug scratch editor). */
  allowDelete?: boolean;
  /** Debug: the selected node's captured run data (Logs → Debug in editor). */
  runData?: WorkflowRunNode | null;
  /** Debug: re-execute this node (staleness-aware). */
  onExecuteNode?: () => void;
  executeBusy?: boolean;
}

/** A trigger node's full output key list (static seed + entity record fields +
 * manual inputs) for the dynamic-content picker. */
function triggerOutputItems(
  node: WorkflowNode,
  metadata: WorkflowMetadata,
): { key: string; label: string }[] {
  const entry = catalogEntry(node.type);
  const items = (entry?.outputs ?? []).map((o) => ({ key: o.key, label: o.label }));
  const entity = entityFor(node, metadata);
  if (entity) {
    for (const f of entity.fields) {
      items.push({ key: `trigger.record.${f.key}`, label: `Record · ${f.label}` });
    }
  }
  const form = formFor(node, metadata);
  if (form) {
    for (const f of form.fields) {
      items.push({ key: `trigger.answers.${f.key}`, label: `Answer · ${f.label}` });
    }
  }
  const inputs = node.config.inputs;
  if (Array.isArray(inputs)) {
    for (const input of inputs as WorkflowManualInput[]) {
      items.push({ key: `trigger.input.${input.key}`, label: `Input · ${input.label || input.key}` });
    }
  }
  return items;
}

/** "N node(s) back" - the n8n distance hint that tells two same-type nodes apart. */
function backHint(depth: number): string {
  return `${depth} node${depth === 1 ? '' : 's'} back`;
}

/** Ancestors of `nodeId` whose outputs are referenceable here (D7), closest
 * first, labelled by unique node name + distance. */
function upstreamGroups(
  doc: WorkflowDefinition,
  nodeId: string,
  metadata: WorkflowMetadata,
): DynamicContentGroup[] {
  const groups: DynamicContentGroup[] = [];
  for (const { node, depth } of ancestorsByDepth(doc, nodeId)) {
    const entry = catalogEntry(node.type);
    if (!entry) continue;
    const sourceLabel = nodeDisplayName(node, entry.label);
    if (node.kind === 'trigger') {
      groups.push({ sourceLabel, hint: backHint(depth), items: triggerOutputItems(node, metadata) });
    } else if (node.kind === 'action') {
      groups.push({
        sourceLabel,
        hint: backHint(depth),
        items: entry.outputs.map((o) => ({ key: `nodes.${node.id}.${o.key}`, label: o.label })),
      });
    }
  }
  return groups;
}

/** Run-context facts for an IF node's rule builder - the same upstream outputs,
 * typed where the metadata knows the type (entity record fields), else string. */
function runContextFacts(
  doc: WorkflowDefinition,
  nodeId: string,
  metadata: WorkflowMetadata,
): RuleFact[] {
  const facts: RuleFact[] = [];
  const push = (key: string, label: string, type: RuleFactType, source: string, sourceLabel: string) =>
    facts.push({ key, label, type, source, sourceLabel });

  for (const { node } of ancestorsByDepth(doc, nodeId)) {
    const entry = catalogEntry(node.type);
    const label = nodeDisplayName(node, entry?.label ?? node.type);
    if (node.kind === 'trigger') {
      push('trigger.actor.name', 'Actor name', 'string', 'trigger.actor', 'Acting user');
      push('trigger.actor.email', 'Actor email', 'string', 'trigger.actor', 'Acting user');
      const entity = entityFor(node, metadata);
      if (entity) {
        for (const f of entity.fields) {
          push(`trigger.record.${f.key}`, f.label, f.type, 'trigger.record', `${entity.label} record`);
        }
      }
      if (node.type === 'entity.status_changed') {
        push('trigger.fromStatus', 'From status', 'string', 'trigger', 'Status change');
        push('trigger.toStatus', 'To status', 'string', 'trigger', 'Status change');
      }
      const form = formFor(node, metadata);
      if (form) {
        for (const f of form.fields) {
          push(`trigger.answers.${f.key}`, f.label, 'string', 'trigger.answers', `${form.name} answers`);
        }
      }
      const inputs = node.config.inputs;
      if (Array.isArray(inputs)) {
        for (const input of inputs as WorkflowManualInput[]) {
          push(`trigger.input.${input.key}`, input.label || input.key, 'string', 'trigger.input', 'Run input');
        }
      }
    } else if (node.kind === 'action') {
      for (const o of entry?.outputs ?? []) {
        push(`nodes.${node.id}.${o.key}`, o.label, 'string', `nodes.${node.id}`, label);
      }
    }
  }
  return facts;
}

/** Reverse-BFS ancestors of a node with their minimum distance (closest first
 * - n8n lists nearest nodes at the top). */
function ancestorsByDepth(doc: WorkflowDefinition, nodeId: string): { node: WorkflowNode; depth: number }[] {
  const parents = new Map<string, string[]>();
  for (const e of doc.edges) parents.set(e.target, [...(parents.get(e.target) ?? []), e.source]);
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  const depthOf = new Map<string, number>();
  let frontier = parents.get(nodeId) ?? [];
  let depth = 1;
  while (frontier.length) {
    const next: string[] = [];
    for (const id of frontier) {
      if (depthOf.has(id)) continue;
      depthOf.set(id, depth);
      next.push(...(parents.get(id) ?? []));
    }
    frontier = next;
    depth++;
  }
  return Array.from(depthOf.entries())
    .map(([id, d]) => ({ node: byId.get(id)!, depth: d }))
    .filter((x) => x.node)
    .sort((a, b) => a.depth - b.depth);
}

/** The triggerable entity a node points at via `config.entityType`. */
function entityFor(node: WorkflowNode, metadata: WorkflowMetadata): WorkflowTriggerableEntity | undefined {
  const type = node.config.entityType;
  if (typeof type !== 'string' || !type) return undefined;
  return metadata.entities.find((e) => e.type === type);
}

/** The published form a `form.submitted` trigger points at via `config.formId`
 * - backs the dynamic `trigger.answers.<key>` outputs (slice 2). */
function formFor(node: WorkflowNode, metadata: WorkflowMetadata): WorkflowFormOption | undefined {
  const id = node.config.formId;
  if (typeof id !== 'string' || !id) return undefined;
  return (metadata.forms ?? []).find((f) => f.id === id);
}

function ManualInputsEditor({
  inputs,
  editing,
  onChange,
}: {
  inputs: WorkflowManualInput[];
  editing: boolean;
  onChange: (next: WorkflowManualInput[]) => void;
}) {
  const update = (i: number, patch: Partial<WorkflowManualInput>) =>
    onChange(inputs.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  return (
    <div className="flex flex-col gap-2" data-testid="manual-inputs-editor">
      {inputs.map((row, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <Input
            value={row.key}
            disabled={!editing}
            placeholder="key"
            aria-label={`Input ${i + 1} key`}
            onChange={(e) => update(i, { key: e.target.value })}
            className="flex-1"
          />
          <Input
            value={row.label}
            disabled={!editing}
            placeholder="label"
            aria-label={`Input ${i + 1} label`}
            onChange={(e) => update(i, { label: e.target.value })}
            className="flex-1"
          />
          {editing && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 text-destructive"
              aria-label={`Remove input ${i + 1}`}
              onClick={() => onChange(inputs.filter((_, idx) => idx !== i))}
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      ))}
      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="add-manual-input"
          onClick={() => onChange([...inputs, { key: '', label: '', type: 'string' }])}
        >
          <Plus className="size-3.5" /> Add input
        </Button>
      )}
      {!inputs.length && !editing && <p className="text-xs text-muted-foreground">No inputs.</p>}
    </div>
  );
}

/** field ← value rows for the entity.update action (D8). */
function AssignmentsEditor({
  assignments,
  fields,
  groups,
  editing,
  onChange,
}: {
  assignments: WorkflowFieldAssignment[];
  fields: WorkflowEntityField[];
  groups: DynamicContentGroup[];
  editing: boolean;
  onChange: (next: WorkflowFieldAssignment[]) => void;
}) {
  const update = (i: number, patch: Partial<WorkflowFieldAssignment>) =>
    onChange(assignments.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  return (
    <div className="flex flex-col gap-2" data-testid="assignments-editor">
      {assignments.map((row, i) => (
        <div key={i} className="flex items-start gap-1.5">
          <div className="w-32 shrink-0">
            <SearchSelect
              options={fields.map((f) => ({ value: f.key, label: f.label }))}
              value={row.field || null}
              onChange={(field) => update(i, { field })}
              ariaLabel={`Field ${i + 1}`}
              placeholder="Field…"
              disabled={!editing}
            />
          </div>
          <div className="flex-1">
            <DynamicContentField
              value={row.value}
              onChange={(value) => update(i, { value })}
              groups={groups}
              placeholder="Value"
              disabled={!editing}
              aria-label={`Value ${i + 1}`}
            />
          </div>
          {editing && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 text-destructive"
              aria-label={`Remove assignment ${i + 1}`}
              onClick={() => onChange(assignments.filter((_, idx) => idx !== i))}
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      ))}
      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="add-assignment"
          onClick={() => onChange([...assignments, { field: '', value: '' }])}
        >
          <Plus className="size-3.5" /> Add field
        </Button>
      )}
      {!assignments.length && !editing && <p className="text-xs text-muted-foreground">No fields set.</p>}
    </div>
  );
}

export function NodeConfigDrawer({
  node,
  doc,
  editing,
  templateOptions,
  metadata,
  onConfigChange,
  onDelete,
  onReplaceNode,
  allowDelete = true,
  runData,
  onExecuteNode,
  executeBusy,
}: NodeConfigDrawerProps) {
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [templatePreviewOpen, setTemplatePreviewOpen] = useState(false);
  if (!node) {
    return (
      <div className="px-1 py-8 text-center text-xs text-muted-foreground">
        Select a node to configure it.
      </div>
    );
  }
  const entry = catalogEntry(node.type);
  const groups = upstreamGroups(doc, node.id, metadata);
  const entity = entityFor(node, metadata);
  const displayName = nodeDisplayName(node, entry?.label ?? node.type);
  const requiresConnection =
    entry && entry.kind === 'action' ? entry.requiresConnection : undefined;
  const missingConnection =
    requiresConnection && metadata.connections && !metadata.connections[requiresConnection];
  const duplicateName =
    node.kind !== 'if' &&
    doc.nodes.some(
      (o) => o.id !== node.id && nodeDisplayName(o, catalogEntry(o.type)?.label ?? o.type) === displayName,
    );
  // Quick-replace within the same kind (ports stay compatible).
  const replaceOptions = (node.kind === 'trigger' ? TRIGGER_CATALOG : ACTION_CATALOG).map((e) => ({
    value: e.type,
    label: e.label,
  }));

  /** Changing the entity invalidates its dependent pickers. */
  const changeEntity = (key: string, value: string) => {
    const patch: WorkflowNodeConfig = { [key]: value };
    for (const dep of ['fromStatus', 'toStatus', 'field'] as const) {
      if (dep in node.config) patch[dep] = '';
    }
    if ('assignments' in node.config) patch.assignments = [];
    onConfigChange(node.id, patch);
  };

  const renderField = (field: NodeFieldDef) => {
    const value = node.config[field.key];
    const labelEl = (
      <Label className="text-xs font-medium text-foreground">
        {field.label}
        {field.required && <span className="text-destructive"> *</span>}
      </Label>
    );
    const wrap = (children: React.ReactNode) => (
      <div key={field.key} className="flex flex-col gap-1.5">
        {labelEl}
        {children}
        {field.help && <p className="text-[11px] text-muted-foreground">{field.help}</p>}
      </div>
    );

    if (field.type === 'inputs') {
      return wrap(
        <ManualInputsEditor
          inputs={Array.isArray(value) ? (value as WorkflowManualInput[]) : []}
          editing={editing}
          onChange={(next) => onConfigChange(node.id, { [field.key]: next })}
        />,
      );
    }

    if (field.type === 'entity') {
      const options = metadata.entities
        .filter((e) => (field.entityFilter === 'status' ? e.hasStatus : true))
        .map((e) => ({ value: e.type, label: e.label }));
      return wrap(
        <SearchSelect
          options={options}
          value={typeof value === 'string' && value ? value : null}
          onChange={(v) => changeEntity(field.key, v)}
          ariaLabel={field.label}
          placeholder="Choose an entity…"
          searchPlaceholder="Search entities…"
          disabled={!editing}
        />,
      );
    }

    if (field.type === 'status') {
      const statuses = entity?.statuses ?? [];
      return wrap(
        <SearchSelect
          options={statuses}
          value={typeof value === 'string' && value ? value : null}
          onChange={(v) => onConfigChange(node.id, { [field.key]: v })}
          ariaLabel={field.label}
          placeholder={entity ? (field.required ? 'Choose a status…' : 'Any status') : 'Choose an entity first'}
          searchPlaceholder="Search statuses…"
          disabled={!editing || !entity}
        />,
      );
    }

    if (field.type === 'field') {
      const fieldOptions = (entity?.fields ?? []).map((f) => ({ value: f.key, label: f.label }));
      return wrap(
        <SearchSelect
          options={fieldOptions}
          value={typeof value === 'string' && value ? value : null}
          onChange={(v) => onConfigChange(node.id, { [field.key]: v })}
          ariaLabel={field.label}
          placeholder={entity ? 'Choose a field…' : 'Choose an entity first'}
          searchPlaceholder="Search fields…"
          disabled={!editing || !entity}
        />,
      );
    }

    if (field.type === 'form') {
      const formOptions = (metadata.forms ?? []).map((f) => ({ value: f.id, label: f.name }));
      return wrap(
        <SearchSelect
          options={formOptions}
          value={typeof value === 'string' && value ? value : null}
          onChange={(v) => onConfigChange(node.id, { [field.key]: v })}
          ariaLabel={field.label}
          placeholder="Choose a form…"
          searchPlaceholder="Search forms…"
          disabled={!editing}
        />,
      );
    }

    if (field.type === 'cron') {
      return wrap(
        <CronBuilder
          key={node.id}
          cron={typeof value === 'string' ? value : ''}
          timezone={typeof node.config.timezone === 'string' ? node.config.timezone : ''}
          disabled={!editing}
          onChange={(cron, timezone) => onConfigChange(node.id, { [field.key]: cron, timezone })}
        />,
      );
    }

    if (field.type === 'assignments') {
      // Only writable fields - the others fail at run time (server whitelist).
      const writable = new Set(entity?.writableFields ?? []);
      const writableFields = (entity?.fields ?? []).filter((f) => writable.has(f.key));
      return wrap(
        <AssignmentsEditor
          assignments={Array.isArray(value) ? (value as WorkflowFieldAssignment[]) : []}
          fields={writableFields}
          groups={groups}
          editing={editing}
          onChange={(next) => onConfigChange(node.id, { [field.key]: next })}
        />,
      );
    }

    if (field.type === 'template') {
      const selected = typeof value === 'string' && value ? value : null;
      const copiedDoc = node.config.doc as TemplateDocument | undefined;
      return wrap(
        <div className="flex flex-col gap-1.5">
          <SearchSelect
            options={templateOptions}
            value={selected}
            onChange={(v) => {
              if (!v) {
                onConfigChange(node.id, { [field.key]: null, doc: null });
                return;
              }
              // Copy the template's block doc for per-use editing (branded).
              void templateEngineService.getTemplate(v).then((t) => {
                // Email picker lists only email templates - never a canvas doc.
                if (t && !isCanvasDoc(t.doc))
                  onConfigChange(node.id, {
                    [field.key]: v,
                    doc: t.doc,
                    subject: t.subject,
                    templateContext: t.context,
                  });
              });
            }}
            ariaLabel={field.label}
            placeholder="Choose a template…"
            searchPlaceholder="Search templates…"
            disabled={!editing}
          />
          {copiedDoc && (
            <>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 self-start"
                onClick={() => setTemplatePreviewOpen(true)}
              >
                <Eye className="size-3.5" /> Edit &amp; preview
              </Button>
              <TemplateContentEditor
                open={templatePreviewOpen}
                onOpenChange={setTemplatePreviewOpen}
                doc={copiedDoc}
                subject={typeof node.config.subject === 'string' ? node.config.subject : ''}
                contextKey={
                  typeof node.config.templateContext === 'string'
                    ? node.config.templateContext
                    : 'status.notification'
                }
                onDocChange={(doc) => onConfigChange(node.id, { doc })}
                onSubjectChange={(subject) => onConfigChange(node.id, { subject })}
                title={displayName}
                disabled={!editing}
              />
            </>
          )}
        </div>,
      );
    }

    if (field.type === 'select') {
      return wrap(
        <SearchSelect
          options={field.options ?? []}
          value={typeof value === 'string' && value ? value : null}
          onChange={(v) => {
            const patch: WorkflowNodeConfig = { [field.key]: v };
            // Switching email.send away from a template → drop the copied doc
            // (the backend renders doc first, so a stale copy would override).
            if (node.type === 'email.send' && field.key === 'mode' && v !== 'template') {
              patch.doc = null;
              patch.templateId = null;
            }
            onConfigChange(node.id, patch);
          }}
          ariaLabel={field.label}
          placeholder="Select…"
          searchPlaceholder="Search…"
          disabled={!editing}
        />,
      );
    }

    // text / textarea - mergeable → dynamic-content field.
    return wrap(
      field.mergeable ? (
        <DynamicContentField
          value={typeof value === 'string' ? value : ''}
          onChange={(v) => onConfigChange(node.id, { [field.key]: v })}
          groups={groups}
          multiline={field.type === 'textarea'}
          placeholder={field.placeholder}
          disabled={!editing}
          aria-label={field.label}
        />
      ) : (
        <Input
          value={typeof value === 'string' ? value : ''}
          disabled={!editing}
          placeholder={field.placeholder}
          aria-label={field.label}
          data-testid={`field-${field.key}`}
          onChange={(e) => onConfigChange(node.id, { [field.key]: e.target.value })}
        />
      ),
    );
  };

  return (
    <div className="flex flex-col gap-4" data-testid="node-config-drawer">
      <div className="flex flex-col gap-1">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {node.kind === 'trigger' ? 'Trigger' : node.kind === 'if' ? 'Condition' : 'Action'}
        </div>
        {editing ? (
          <Input
            value={displayName}
            aria-label="Node name"
            data-testid="node-name"
            className={cn('h-8 font-semibold', duplicateName && 'border-destructive')}
            onChange={(e) => onConfigChange(node.id, { name: e.target.value })}
          />
        ) : (
          <div className="text-sm font-semibold text-foreground">{displayName}</div>
        )}
        {duplicateName && (
          <p className="text-[11px] text-destructive" data-testid="node-name-error">
            Another node already uses this name - names must be unique.
          </p>
        )}
        {editing && onReplaceNode && node.kind !== 'if' && (
          <div className="mt-1 flex flex-col gap-1">
            <Label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {node.kind === 'trigger' ? 'Trigger type' : 'Action type'}
            </Label>
            <SearchSelect
              options={replaceOptions}
              value={node.type}
              onChange={(v) => v !== node.type && onReplaceNode(node.id, v)}
              ariaLabel="Node type"
              searchPlaceholder="Search types…"
            />
          </div>
        )}
        {entry?.description && (
          <p className="text-xs text-muted-foreground">{entry.description}</p>
        )}
      </div>

      {onExecuteNode && (
        <div className="flex flex-col gap-2 rounded-md border border-amber-400/40 bg-amber-50/50 p-2.5 dark:bg-amber-950/20" data-testid="node-run-data">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Run data
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7"
              disabled={executeBusy}
              onClick={onExecuteNode}
              data-testid="execute-node"
            >
              <Play className="size-3" /> Execute node
            </Button>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Output
            </div>
            <pre className="max-h-32 overflow-auto rounded bg-muted p-1.5 text-[11px] text-foreground">
              {runData?.outputJson == null ? '-' : JSON.stringify(runData.outputJson, null, 2)}
            </pre>
          </div>
          {runData?.error && (
            <pre className="overflow-auto rounded bg-destructive/10 p-1.5 text-[11px] text-destructive">
              {runData.error}
            </pre>
          )}
        </div>
      )}

      {missingConnection && (
        <div
          className="flex items-start gap-2 rounded-md border border-amber-400/50 bg-amber-50/60 p-2.5 text-xs text-amber-700 dark:bg-amber-950/20 dark:text-amber-400"
          data-testid="missing-connection-warning"
        >
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          <span>
            No {requiresConnection} connection is set up for this workspace.{' '}
            {requiresConnection === 'email'
              ? 'Outgoing mail won’t be delivered until one is connected.'
              : 'Files will fall back to local storage until one is connected.'}
          </span>
        </div>
      )}

      {node.kind === 'if' ? (
        <div className="flex flex-col gap-1.5" data-testid="if-conditions">
          <Label className="text-xs font-medium text-foreground">Conditions</Label>
          <RuleBuilder
            key={node.id}
            facts={runContextFacts(doc, node.id, metadata)}
            value={(node.config.conditions as RuleGroup | null) ?? null}
            onChange={(group) => onConfigChange(node.id, { conditions: group })}
            disabled={!editing}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-3.5">
          {node.type === 'email.send' && node.config.mode === 'custom' && (
            <div className="flex flex-col gap-1.5">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 self-end"
                onClick={() => setEmailDialogOpen(true)}
              >
                <Maximize2 className="size-3.5" /> Expand
              </Button>
              <Dialog open={emailDialogOpen} onOpenChange={setEmailDialogOpen}>
                <DialogContent className="max-w-4xl">
                  <DialogHeader>
                    <DialogTitle>{displayName}</DialogTitle>
                  </DialogHeader>
                  <DialogBody className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                    <div className="flex flex-col gap-3">
                      <div className="flex flex-col gap-1.5">
                        <Label className="text-xs font-medium text-muted-foreground">Subject</Label>
                        <DynamicContentField
                          value={typeof node.config.subject === 'string' ? node.config.subject : ''}
                          onChange={(v) => onConfigChange(node.id, { subject: v })}
                          groups={groups}
                          disabled={!editing}
                          aria-label="Subject"
                        />
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <Label className="text-xs font-medium text-muted-foreground">Body</Label>
                        <DynamicContentField
                          value={typeof node.config.body === 'string' ? node.config.body : ''}
                          onChange={(v) => onConfigChange(node.id, { body: v })}
                          groups={groups}
                          multiline
                          rows={16}
                          disabled={!editing}
                          aria-label="Body"
                        />
                      </div>
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="text-xs font-medium text-muted-foreground">
                        Preview · tokens resolve at run time
                      </Label>
                      <div className="flex min-h-9 items-center rounded-md border border-dashed border-input bg-muted/40 px-3 py-1.5 text-sm font-medium text-foreground">
                        {typeof node.config.subject === 'string' && node.config.subject ? (
                          node.config.subject
                        ) : (
                          <span className="font-normal text-muted-foreground">(empty subject)</span>
                        )}
                      </div>
                      <div className="min-h-40 flex-1 whitespace-pre-wrap rounded-md border border-dashed border-input bg-muted/40 px-3 py-2 text-sm text-foreground">
                        {typeof node.config.body === 'string' && node.config.body ? (
                          node.config.body
                        ) : (
                          <span className="text-muted-foreground">(empty body)</span>
                        )}
                      </div>
                    </div>
                  </DialogBody>
                </DialogContent>
              </Dialog>
            </div>
          )}
          {(entry?.fields ?? [])
            .filter((f) => !f.showWhen || node.config[f.showWhen.field] === f.showWhen.value)
            .map(renderField)}
        </div>
      )}

      {editing && allowDelete && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start text-destructive"
          data-testid="delete-node"
          onClick={() => onDelete(node.id)}
        >
          <Trash2 className="size-3.5" /> Delete node
        </Button>
      )}
    </div>
  );
}
