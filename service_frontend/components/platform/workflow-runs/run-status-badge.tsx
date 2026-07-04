'use client';

import { Badge, type BadgeProps } from '@/components/ui/badge';
import type { WorkflowNodeRunStatus, WorkflowRunStatus } from '@/types/workflows';

const RUN_VARIANT: Record<WorkflowRunStatus, BadgeProps['variant']> = {
  success: 'success',
  failed: 'destructive',
  running: 'warning',
  pending: 'secondary',
  cancelled: 'secondary',
};

const RUN_LABEL: Record<WorkflowRunStatus, string> = {
  success: 'Success',
  failed: 'Failed',
  running: 'Running',
  pending: 'Pending',
  cancelled: 'Cancelled',
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
};

export function NodeRunStatusBadge({ status }: { status: WorkflowNodeRunStatus }) {
  return (
    <Badge variant={NODE_VARIANT[status]} appearance="light" size="sm">
      {status}
    </Badge>
  );
}
