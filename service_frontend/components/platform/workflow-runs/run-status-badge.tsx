'use client';

import { Badge, type BadgeProps } from '@/components/ui/badge';
import type { WorkflowNodeRunStatus, WorkflowRunStatus } from '@/types/workflows';

const RUN_VARIANT: Record<WorkflowRunStatus, BadgeProps['variant']> = {
  success: 'success',
  failed: 'destructive',
  running: 'warning',
  pending: 'secondary',
  cancelled: 'secondary',
  // Parked at an Ask a question / Wait / Business hours node (plan 31 S6,
  // AC-WFP-65) - a distinct info tint, never destructive/warning (it is not
  // an error, just a suspended run awaiting an answer/deadline).
  waiting: 'info',
};

const RUN_LABEL: Record<WorkflowRunStatus, string> = {
  success: 'Success',
  failed: 'Failed',
  running: 'Running',
  pending: 'Pending',
  cancelled: 'Cancelled',
  waiting: 'Waiting',
};

export function RunStatusBadge({ status, size }: { status: WorkflowRunStatus; size?: BadgeProps['size'] }) {
  return (
    <Badge variant={RUN_VARIANT[status]} appearance="light" size={size}>
      {RUN_LABEL[status]}
    </Badge>
  );
}

const NODE_VARIANT: Record<WorkflowNodeRunStatus, BadgeProps['variant']> = {
  success: 'success',
  failed: 'destructive',
  running: 'warning',
  pending: 'secondary',
  skipped: 'secondary',
  waiting: 'info',
};

const NODE_LABEL: Record<WorkflowNodeRunStatus, string> = {
  success: 'success',
  failed: 'failed',
  running: 'running',
  pending: 'pending',
  skipped: 'skipped',
  waiting: 'waiting',
};

export function NodeRunStatusBadge({ status }: { status: WorkflowNodeRunStatus }) {
  return (
    <Badge variant={NODE_VARIANT[status]} appearance="light" size="sm">
      {NODE_LABEL[status]}
    </Badge>
  );
}
