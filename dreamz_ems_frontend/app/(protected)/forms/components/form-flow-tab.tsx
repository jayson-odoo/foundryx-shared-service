'use client';

/** Flow tab (plan sprint-3/01 D4/D18) — the form's OWN submission pipeline on
 * the existing status canvas, scope-filtered (`scopeId = formId`). Statuses
 * here are tenant-owned from birth (materialized at form creation), so the
 * canvas edits apply directly — no platform fork gymnastics. */
import { EntityFlow, type LayoutController } from '@/components/platform/status-engine';
import { useStatusGraph } from '@/hooks/use-status-engine';

export const FORM_SUBMISSION_ENTITY = 'form_submission';

export interface FormFlowTabProps {
  formId: string;
  formName: string;
  editing: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  layoutController?: React.MutableRefObject<LayoutController | null>;
}

export function FormFlowTab({
  formId,
  formName,
  editing,
  onDirtyChange,
  layoutController,
}: FormFlowTabProps) {
  const engine = useStatusGraph(FORM_SUBMISSION_ENTITY, formId);

  return (
    <EntityFlow
      entityType={FORM_SUBMISSION_ENTITY}
      entityLabel={`${formName} submission`}
      engine={engine}
      editing={editing}
      onDirtyChange={onDirtyChange}
      layoutController={layoutController}
    />
  );
}
