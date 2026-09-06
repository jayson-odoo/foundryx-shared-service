/**
 * Workflow-metadata service boundary (plan sprint-2/09). UI → hook → THIS →
 * api-client. Returns the triggerable entity catalog (fact sources + statuses)
 * the editor needs to configure entity/status/field nodes. Phase A is
 * mock-bound; Phase B swaps to `GET /workflow-metadata` in one line.
 */
import type { WorkflowMetadata } from '@/types/workflows';
import { realWorkflowMetadataService } from './workflow-metadata-service.real';
import { mockOmnichannelWorkflowMetadata } from './workflow-metadata-service.mock';

export interface WorkflowMetadataService {
  getMetadata(): Promise<WorkflowMetadata>;
}

// Phase B: bound to the real api-client (GET /workflows/metadata). The mock is
// retained in workflow-metadata-service.mock.ts for component tests.
export const workflowMetadataService: WorkflowMetadataService = {
  async getMetadata() {
    const metadata = await realWorkflowMetadataService.getMetadata();
    // S0 MOCK - swap to real in S3 (plan 31): `omnichannelWorkspaces` and
    // `workflows` are the plan-31 catalog additions - the backend registry
    // and the `GET /workflows/metadata` response additions land in S1/S2, so
    // until then only THESE two keys are mocked here; everything else above
    // is the tenant's real data. `??` never overrides a real backend value
    // once S1/S2 ship it.
    return {
      ...metadata,
      omnichannelWorkspaces:
        metadata.omnichannelWorkspaces ??
        mockOmnichannelWorkflowMetadata.omnichannelWorkspaces,
      workflows: metadata.workflows ?? mockOmnichannelWorkflowMetadata.workflows,
    };
  },
};
