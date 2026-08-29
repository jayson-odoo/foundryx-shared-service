import type { Workflow, WorkflowMetadata } from '@/types/workflows';
import { validateDefinition } from '@/lib/workflow-doc';

/** Shared frontend publish gate for the editor and list/bulk actions. */
export function workflowPublishIssue(
  workflow: Workflow,
  metadata: WorkflowMetadata,
  canCode: boolean,
): string | null {
  const definitionIssue = validateDefinition(
    workflow.draftDefinition,
    metadata,
  ).find((issue) => issue.level === 'error');
  if (definitionIssue) return definitionIssue.message;
  const codeNodes = workflow.draftDefinition.nodes.filter(
    (node) => node.type === 'code.run',
  );
  if (codeNodes.length > 0 && !canCode)
    return 'You need the workflows.code permission to publish Code nodes.';
  if (metadata.codeRunnerAvailable !== false || codeNodes.length === 0)
    return null;
  // Real backends may omit the embedded published definition. Do not falsely
  // block an unchanged stored Code node when there is no comparison baseline.
  if (workflow.currentVersionId && !workflow.currentVersion?.definition)
    return null;
  const baseline = workflow.currentVersion?.definition;
  return codeNodes.some((node) => {
    const previous = baseline?.nodes.find(
      (candidate) => candidate.id === node.id,
    );
    return (
      !previous ||
      JSON.stringify(previous.config) !== JSON.stringify(node.config)
    );
  })
    ? 'Code runner is unavailable. Publishing changed Code nodes is blocked.'
    : null;
}
