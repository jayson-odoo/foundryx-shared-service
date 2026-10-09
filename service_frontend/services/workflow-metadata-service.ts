/**
 * Workflow-metadata service boundary (plan sprint-2/09). UI → hook → THIS →
 * api-client. Returns the triggerable entity catalog (fact sources + statuses)
 * the editor needs to configure entity/status/field nodes, plus the plan-31
 * omnichannel additions (`omnichannelWorkspaces`, `workflows`) - all now live
 * from `GET /workflows/metadata` (plan 31 S3: the S0 mock merge is gone, the
 * backend has carried these keys since S1).
 */
import type { WorkflowMetadata } from '@/types/workflows';
import { realWorkflowMetadataService } from './workflow-metadata-service.real';

export interface WorkflowMetadataService {
  getMetadata(): Promise<WorkflowMetadata>;
}

export const workflowMetadataService: WorkflowMetadataService =
  realWorkflowMetadataService;
