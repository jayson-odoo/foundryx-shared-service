/**
 * Mock workflow-metadata service (Phase A) - the v1 instrumented triggerable
 * entity set (plan sprint-2/09 D6: user, role, tenant, connection, template,
 * workflow). Each entity = a rule-engine fact source; status-engine adopters
 * (tenant) carry their statuses. Phase B swaps the binding to `GET
 * /workflow-metadata` in workflow-metadata-service.ts.
 */
import { CODE_CAPABILITIES_FALLBACK } from '@/components/platform/workflow-canvas/code-editor';
import type {
  WorkflowMetadata,
  WorkflowOmnichannelWorkspace,
  WorkflowRefOption,
  WorkflowTriggerableEntity,
} from '@/types/workflows';
import { delay } from './mock-query';

const ENTITIES: WorkflowTriggerableEntity[] = [
  {
    type: 'user',
    writableFields: ['name', 'status'],
    label: 'User',
    hasStatus: false,
    statuses: [],
    supportsShortcut: false,
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
    supportsShortcut: false,
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
    supportsShortcut: false,
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
    supportsShortcut: false,
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
    supportsShortcut: false,
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
    supportsShortcut: false,
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

// Plan 31 (omnichannel workflow parity) - S0 MOCK. The registry-driven
// triggers/steps and the `GET /workflows/metadata` additions land in S1/S2;
// until then `workflow-metadata-service.ts` merges this in behind the real
// call so the palette/pickers are usable on the mock. Swap to real in S3.
const OMNICHANNEL_WORKSPACES: WorkflowOmnichannelWorkspace[] = [
  {
    id: 'ws-demo',
    name: 'General',
    contactTags: [
      { id: 'tag-vip', name: 'VIP' },
      { id: 'tag-lead', name: 'Lead' },
    ],
    contactFields: [
      { key: 'company', label: 'Company', type: 'string' },
      { key: 'orderCount', label: 'Order count', type: 'number' },
    ],
    lifecycleStages: [
      { id: 'stage-new', name: 'New' },
      { id: 'stage-qualified', name: 'Qualified' },
      { id: 'stage-customer', name: 'Customer' },
    ],
    closeReasons: [
      { id: 'reason-resolved', name: 'Resolved', isActive: true },
      { id: 'reason-spam', name: 'Spam', isActive: true },
      { id: 'reason-legacy', name: 'Legacy', isActive: false },
    ],
    members: [{ id: 'user-demo', name: 'Demo Admin' }],
    templates: [
      { id: 'tpl-welcome', name: 'welcome_message', status: 'APPROVED' },
      { id: 'tpl-order-update', name: 'order_update', status: 'PENDING' },
    ],
  },
  {
    id: 'ws-sales',
    name: 'Sales',
    contactTags: [{ id: 'tag-hot', name: 'Hot lead' }],
    contactFields: [{ key: 'dealSize', label: 'Deal size', type: 'number' }],
    lifecycleStages: [
      { id: 'stage-prospect', name: 'Prospect' },
      { id: 'stage-won', name: 'Won' },
    ],
    closeReasons: [{ id: 'reason-lost', name: 'Lost', isActive: true }],
    members: [{ id: 'user-demo', name: 'Demo Admin' }],
    templates: [{ id: 'tpl-followup', name: 'sales_followup', status: 'APPROVED' }],
  },
];

const WORKFLOWS: WorkflowRefOption[] = [
  { id: 'wf-onboarding', name: 'Contact onboarding' },
  { id: 'wf-nurture', name: 'Lead nurture' },
];

/** ONLY the plan-31 additions - merged over the real metadata response
 * (`workflow-metadata-service.ts`, `// S0 MOCK - swap to real in S3`). */
export const mockOmnichannelWorkflowMetadata: Pick<
  WorkflowMetadata,
  'omnichannelWorkspaces' | 'workflows'
> = {
  omnichannelWorkspaces: OMNICHANNEL_WORKSPACES,
  workflows: WORKFLOWS,
};

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
        ...mockOmnichannelWorkflowMetadata,
      },
      120,
    );
  },
};
