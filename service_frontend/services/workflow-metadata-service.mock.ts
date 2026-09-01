/**
 * Mock workflow-metadata service (Phase A) - the v1 instrumented triggerable
 * entity set (plan sprint-2/09 D6: user, role, tenant, connection, template,
 * workflow). Each entity = a rule-engine fact source; status-engine adopters
 * (tenant) carry their statuses. Phase B swaps the binding to `GET
 * /workflow-metadata` in workflow-metadata-service.ts.
 */
import { CODE_CAPABILITIES_FALLBACK } from '@/components/platform/workflow-canvas/code-editor';
import type { WorkflowMetadata, WorkflowTriggerableEntity } from '@/types/workflows';
import { delay } from './mock-query';

const ENTITIES: WorkflowTriggerableEntity[] = [
  {
    type: 'user',
    writableFields: ['name', 'status'],
    label: 'User',
    hasStatus: false,
    statuses: [],
    fields: [
      { key: 'email', label: 'Email', type: 'string' },
      { key: 'name', label: 'Name', type: 'string' },
      { key: 'createdAt', label: 'Created at', type: 'date' },
    ],
  },
  {
    type: 'role',
    writableFields: ['name', 'description'],
    label: 'Role',
    hasStatus: false,
    statuses: [],
    fields: [
      { key: 'name', label: 'Name', type: 'string' },
      { key: 'description', label: 'Description', type: 'string' },
      { key: 'isSystem', label: 'Is system', type: 'boolean' },
    ],
  },
  {
    type: 'tenant',
    writableFields: ['name'],
    label: 'Tenant',
    hasStatus: true,
    statuses: [
      { value: 'active', label: 'Active' },
      { value: 'suspended', label: 'Suspended' },
      { value: 'archived', label: 'Archived' },
    ],
    fields: [
      { key: 'name', label: 'Name', type: 'string' },
      { key: 'slug', label: 'Slug', type: 'string' },
      { key: 'isPlatform', label: 'Is platform', type: 'boolean' },
      { key: 'userCount', label: 'User count', type: 'number' },
      { key: 'createdAt', label: 'Created at', type: 'date' },
    ],
  },
  {
    type: 'connection',
    writableFields: [],
    label: 'Connection',
    hasStatus: false,
    statuses: [],
    fields: [
      { key: 'provider', label: 'Provider', type: 'string' },
      { key: 'type', label: 'Type', type: 'string' },
      { key: 'status', label: 'Status', type: 'string' },
    ],
  },
  {
    type: 'template',
    writableFields: ['name', 'subject'],
    label: 'Email template',
    hasStatus: false,
    statuses: [],
    fields: [
      { key: 'name', label: 'Name', type: 'string' },
      { key: 'key', label: 'Key', type: 'string' },
      { key: 'context', label: 'Context', type: 'string' },
    ],
  },
  {
    type: 'workflow',
    writableFields: ['name', 'description'],
    label: 'Workflow',
    hasStatus: false,
    statuses: [],
    fields: [
      { key: 'name', label: 'Name', type: 'string' },
      { key: 'isActive', label: 'Is active', type: 'boolean' },
      { key: 'triggerType', label: 'Trigger type', type: 'string' },
    ],
  },
];

// Published forms for the `form.submitted` trigger picker (slice 2). Fields =
// the published version's answer keys → dynamic `trigger.answers.<key>` outputs.
const FORMS = [
  {
    id: 'form-reg',
    name: 'Event Registration',
    fields: [
      { key: 'name', label: 'Full name' },
      { key: 'email', label: 'Email' },
      { key: 'tshirt', label: 'T-shirt size' },
    ],
  },
  {
    id: 'form-paper',
    name: 'Paper Submission',
    fields: [
      { key: 'title', label: 'Title' },
      { key: 'abstract', label: 'Abstract' },
    ],
  },
];

export const mockWorkflowMetadataService = {
  getMetadata(): Promise<WorkflowMetadata> {
    return delay(
      {
        entities: ENTITIES,
        connections: { email: true, storage: false },
        forms: FORMS,
        codeRunnerAvailable: true,
        codeCapabilities: CODE_CAPABILITIES_FALLBACK,
        omnichannelChannels: [{ id: 'chn-demo', name: 'Demo channel' }],
        aiAgents: [{ id: 'agent-demo', name: 'Demo classifier', model: 'stub' }],
      },
      120,
    );
  },
};
