/**
 * Workflow-metadata service boundary (plan sprint-2/09). UI → hook → THIS →
 * api-client. Returns the triggerable entity catalog (fact sources + statuses)
 * the editor needs to configure entity/status/field nodes. Phase A is
 * mock-bound; Phase B swaps to `GET /workflow-metadata` in one line.
 */
import type { WorkflowMetadata } from '@/types/workflows';
import { realWorkflowMetadataService } from './workflow-metadata-service.real';

export interface WorkflowMetadataService {
  getMetadata(): Promise<WorkflowMetadata>;
}

// Phase B: bound to the real api-client (GET /workflows/metadata). The mock is
// retained in workflow-metadata-service.mock.ts for component tests.
export const workflowMetadataService: WorkflowMetadataService = realWorkflowMetadataService;
