/**
 * Real workflow-metadata service (plan sprint-2/09 Phase B) - GET
 * /workflows/metadata returns the tenant's triggerable entities with resolved
 * statuses (real status ids) + record fields. Swaps the Phase A mock.
 */
import { apiFetch } from '@/lib/api-client';
import type { WorkflowMetadata } from '@/types/workflows';
import type { WorkflowMetadataService } from './workflow-metadata-service';

export const realWorkflowMetadataService: WorkflowMetadataService = {
  getMetadata() {
    return apiFetch<WorkflowMetadata>('/workflows/metadata');
  },
};
