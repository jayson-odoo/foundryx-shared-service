'use client';

/** Editor tab (plan sprint-2/08 D15): primary toolbar (Run / Publish /
 * Unpublish) above the canvas. Run executes the draft immediately (no publish
 * needed, D13); Publish arms the trigger (D4); Unpublish disarms it. The
 * Active master-switch lives in Settings. When a run is loaded for debugging
 * (Logs → "Debug in editor"), a banner + per-node data + Execute appear. */
import { Bug, CloudUpload, Play, RefreshCw, Rocket, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { WorkflowCanvas, type TemplateOption } from '@/components/platform/workflow-canvas';
import type { WorkflowDebugBundle } from '@/components/platform/workflow-canvas';
import type { Workflow, WorkflowDefinition, WorkflowMetadata } from '@/types/workflows';

export interface WorkflowEditorTabProps {
  workflow: Workflow;
  doc: WorkflowDefinition;
  onDocChange: (doc: WorkflowDefinition) => void;
  editing: boolean;
  canManage: boolean;
  templateOptions: TemplateOption[];
  metadata: WorkflowMetadata;
  busy: boolean;
  onPublish: () => void;
  onUnpublish: () => void;
  onRun: () => void;
  /** Present while debugging a loaded run (Logs → Debug in editor). */
  debug?: WorkflowDebugBundle | null;
  onExecuteAll?: () => void;
  onExitDebug?: () => void;
}

export function WorkflowEditorTab({
  workflow,
  doc,
  onDocChange,
  editing,
  canManage,
  templateOptions,
  metadata,
  busy,
  onPublish,
  onUnpublish,
  onRun,
  debug,
  onExecuteAll,
  onExitDebug,
}: WorkflowEditorTabProps) {
  const isPublished = workflow.currentVersionId !== null;

  return (
    <div className="flex flex-col gap-3" data-testid="workflow-editor-tab">
      {debug ? (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-400/50 bg-amber-50 px-3 py-2 dark:bg-amber-950/30"
          data-testid="debug-banner"
        >
          <div className="flex items-center gap-2 text-sm">
            <Bug className="size-4 text-amber-600" />
            <span className="font-medium text-foreground">Debugging a past run.</span>
            <span className="text-muted-foreground">
              Each node shows that run’s data - fix the flow here and it carries to future runs.
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={onExecuteAll} disabled={busy} data-testid="execute-workflow">
              <RefreshCw className="size-3.5" /> Execute workflow
            </Button>
            <Button variant="ghost" size="sm" onClick={onExitDebug} data-testid="exit-debug">
              <X className="size-3.5" /> Exit debug
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2">
          <div className="flex items-center gap-2">
            {workflow.isActive && isPublished ? (
              <Badge variant="success" appearance="light" size="sm">Live</Badge>
            ) : isPublished ? (
              <Badge variant="secondary" appearance="light" size="sm">Published · inactive</Badge>
            ) : (
              <Badge variant="secondary" appearance="light" size="sm">Not published</Badge>
            )}
            {isPublished && workflow.hasUnpublishedChanges && (
              <Badge variant="warning" appearance="light" size="sm" data-testid="unpublished-badge">
                Unpublished changes
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={busy} onClick={onRun} data-testid="workflow-run">
              <Play className="size-3.5" /> Run
            </Button>
            {canManage && isPublished && (
              <Button variant="outline" size="sm" disabled={busy} onClick={onUnpublish} data-testid="workflow-unpublish">
                Unpublish
              </Button>
            )}
            {canManage && (
              <Button
                size="sm"
                disabled={busy || (isPublished && !workflow.hasUnpublishedChanges)}
                onClick={onPublish}
                data-testid="workflow-publish"
              >
                {isPublished ? <CloudUpload className="size-3.5" /> : <Rocket className="size-3.5" />}
                {isPublished ? 'Publish changes' : 'Publish'}
              </Button>
            )}
          </div>
        </div>
      )}

      <WorkflowCanvas
        doc={doc}
        onChange={onDocChange}
        editing={editing}
        templateOptions={templateOptions}
        metadata={metadata}
        debug={debug}
      />
    </div>
  );
}
