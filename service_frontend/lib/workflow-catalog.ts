/**
 * Frontend node catalog (plan sprint-2/08 D8, fanned out in sprint-2/09 D7/D8)
 * - mirror of the backend `app/workflow_engine/registry.py` TriggerDef/
 * ActionDef. Drives the palette, the config drawer (field schema), and the
 * dynamic-content picker (output schema). The entity triggers expose dynamic
 * `trigger.record.*` outputs resolved from the chosen entity's metadata (the
 * drawer injects them - the catalog lists only the static seed).
 */
import type {
  ActionCatalogEntry,
  IfCatalogEntry,
  NodeCatalogEntry,
  TriggerCatalogEntry,
} from '@/types/workflows';

/** Output seed shared by every entity trigger (record id + actor + action).
 * The chosen entity's fields are appended as `trigger.record.<field>` live. */
const ENTITY_TRIGGER_OUTPUTS = [
  { key: 'trigger.record.id', label: 'Record · id' },
  { key: 'trigger.action', label: 'Action' },
  { key: 'trigger.actor.name', label: 'Actor name' },
  { key: 'trigger.actor.email', label: 'Actor email' },
];

export const TRIGGER_CATALOG: TriggerCatalogEntry[] = [
  {
    kind: 'trigger',
    type: 'manual',
    label: 'Manual',
    description: 'Run on demand from a button (with optional inputs).',
    icon: 'MousePointerClick',
    category: 'Triggers',
    fields: [
      {
        key: 'inputs',
        label: 'Run inputs',
        type: 'inputs',
      },
    ],
    // Manual inputs append `trigger.input.<key>` dynamically (resolved by the
    // picker from the node config); the static seed is the run metadata.
    outputs: [
      { key: 'trigger.triggeredBy', label: 'Triggered by' },
      { key: 'trigger.actor.name', label: 'Actor name' },
      { key: 'trigger.actor.email', label: 'Actor email' },
    ],
  },
  {
    kind: 'trigger',
    type: 'entity.created',
    label: 'Record created',
    description: 'Fires when a record of the chosen entity is created.',
    icon: 'FilePlus2',
    category: 'Triggers',
    fields: [{ key: 'entityType', label: 'Entity', type: 'entity', required: true }],
    outputs: ENTITY_TRIGGER_OUTPUTS,
  },
  {
    kind: 'trigger',
    type: 'entity.updated',
    label: 'Record updated',
    description: 'Fires when a record of the chosen entity is updated.',
    icon: 'FilePenLine',
    category: 'Triggers',
    fields: [{ key: 'entityType', label: 'Entity', type: 'entity', required: true }],
    outputs: [...ENTITY_TRIGGER_OUTPUTS, { key: 'trigger.changedFields', label: 'Changed fields' }],
  },
  {
    kind: 'trigger',
    type: 'entity.deleted',
    label: 'Record deleted',
    description: 'Fires when a record of the chosen entity is deleted.',
    icon: 'FileX',
    category: 'Triggers',
    fields: [{ key: 'entityType', label: 'Entity', type: 'entity', required: true }],
    outputs: ENTITY_TRIGGER_OUTPUTS,
  },
  {
    kind: 'trigger',
    type: 'entity.field_changed',
    label: 'Field changed',
    description: 'Fires when a specific field on the chosen entity changes.',
    icon: 'PencilLine',
    category: 'Triggers',
    fields: [
      { key: 'entityType', label: 'Entity', type: 'entity', required: true },
      { key: 'field', label: 'Field', type: 'field', required: true },
    ],
    outputs: [...ENTITY_TRIGGER_OUTPUTS, { key: 'trigger.changedFields', label: 'Changed fields' }],
  },
  {
    kind: 'trigger',
    type: 'entity.status_changed',
    label: 'Status changed',
    description: 'Fires when the chosen entity moves between statuses.',
    icon: 'Activity',
    category: 'Triggers',
    fields: [
      { key: 'entityType', label: 'Entity', type: 'entity', required: true, entityFilter: 'status' },
      { key: 'fromStatus', label: 'From status', type: 'status' },
      { key: 'toStatus', label: 'To status', type: 'status' },
    ],
    outputs: [
      { key: 'trigger.record.id', label: 'Record · id' },
      { key: 'trigger.fromStatus', label: 'From status' },
      { key: 'trigger.toStatus', label: 'To status' },
      { key: 'trigger.actor.name', label: 'Actor name' },
    ],
  },
  {
    kind: 'trigger',
    type: 'schedule.cron',
    label: 'Schedule',
    description: 'Runs on a recurring schedule in a chosen timezone.',
    icon: 'CalendarClock',
    category: 'Triggers',
    fields: [{ key: 'cron', label: 'Runs', type: 'cron', required: true }],
    outputs: [{ key: 'trigger.firedAt', label: 'Fired at' }],
  },
  {
    kind: 'trigger',
    type: 'form.submitted',
    label: 'Form submitted',
    description: 'Fires when a chosen form receives a submission.',
    icon: 'ClipboardCheck',
    category: 'Triggers',
    fields: [{ key: 'formId', label: 'Form', type: 'form', required: true }],
    // `trigger.answers.<key>` outputs are dynamic per selected form (resolved by
    // the picker from the workflow metadata); the static seed is the run meta.
    outputs: [
      { key: 'trigger.formId', label: 'Form id' },
      { key: 'trigger.submissionId', label: 'Submission id' },
    ],
  },
  {
    kind: 'trigger',
    type: 'omnichannel.message_received',
    label: 'Incoming omnichannel message',
    description: 'Fires when a WhatsApp message arrives on a chosen channel (or any channel).',
    icon: 'MessageCircle',
    category: 'Triggers',
    module: 'omnichannel',
    fields: [{ key: 'channelId', label: 'Channel', type: 'omnichannelChannel' }],
    outputs: [
      { key: 'trigger.message.id', label: 'Message · id' },
      { key: 'trigger.message.text', label: 'Message · text' },
      { key: 'trigger.message.type', label: 'Message · type' },
      { key: 'trigger.message.mediaUrl', label: 'Message · media URL' },
      { key: 'trigger.contact.id', label: 'Contact · id' },
      { key: 'trigger.contact.name', label: 'Contact · name' },
      { key: 'trigger.contact.phone', label: 'Contact · phone' },
      { key: 'trigger.channel.id', label: 'Channel · id' },
      { key: 'trigger.channel.name', label: 'Channel · name' },
      { key: 'trigger.conversationId', label: 'Conversation id' },
    ],
  },
];

export const ACTION_CATALOG: ActionCatalogEntry[] = [
  {
    kind: 'action',
    type: 'email.send',
    label: 'Send email',
    description: 'Render a template and enqueue it to the outbox.',
    icon: 'Mail',
    category: 'Actions',
    requiresConnection: 'email',
    fields: [
      {
        key: 'mode',
        label: 'Email type',
        type: 'select',
        options: [
          { value: 'template', label: 'Use a template' },
          { value: 'custom', label: 'Write a custom email' },
        ],
      },
      {
        key: 'templateId',
        label: 'Template',
        type: 'template',
        required: true,
        showWhen: { field: 'mode', value: 'template' },
      },
      {
        key: 'subject',
        label: 'Subject',
        type: 'text',
        required: true,
        mergeable: true,
        showWhen: { field: 'mode', value: 'custom' },
      },
      {
        key: 'body',
        label: 'Body',
        type: 'textarea',
        required: true,
        mergeable: true,
        showWhen: { field: 'mode', value: 'custom' },
      },
      {
        key: 'to',
        label: 'To',
        type: 'text',
        required: true,
        mergeable: true,
        placeholder: '{{ trigger.input.email }}',
      },
      {
        key: 'subjectOverride',
        label: 'Subject override',
        type: 'text',
        mergeable: true,
        showWhen: { field: 'mode', value: 'template' },
      },
    ],
    outputs: [
      { key: 'messageId', label: 'Message id' },
      { key: 'status', label: 'Enqueue status' },
    ],
  },
  {
    kind: 'action',
    type: 'storage.put',
    label: 'Store a file',
    description: 'Write content to storage and output its URL + metadata.',
    icon: 'HardDriveUpload',
    category: 'Actions',
    requiresConnection: 'storage',
    fields: [
      {
        key: 'key',
        label: 'Storage key',
        type: 'text',
        required: true,
        mergeable: true,
        placeholder: 'reports/{{ trigger.record.id }}.txt',
      },
      { key: 'content', label: 'Content', type: 'textarea', required: true, mergeable: true },
    ],
    outputs: [
      { key: 'url', label: 'URL' },
      { key: 'key', label: 'Key' },
      { key: 'size', label: 'Size (bytes)' },
      { key: 'mime', label: 'MIME type' },
    ],
  },
  {
    kind: 'action',
    type: 'storage.get',
    label: 'Resolve a file',
    description: 'Resolve a stored key to a URL + metadata (no bytes loaded).',
    icon: 'HardDriveDownload',
    category: 'Actions',
    requiresConnection: 'storage',
    fields: [
      { key: 'key', label: 'Storage key', type: 'text', required: true, mergeable: true },
    ],
    outputs: [
      { key: 'url', label: 'URL' },
      { key: 'size', label: 'Size (bytes)' },
      { key: 'mime', label: 'MIME type' },
    ],
  },
  {
    kind: 'action',
    type: 'storage.delete',
    label: 'Delete a file',
    description: 'Permanently delete a stored object by key.',
    icon: 'Trash2',
    category: 'Actions',
    requiresConnection: 'storage',
    destructive: true,
    fields: [
      { key: 'key', label: 'Storage key', type: 'text', required: true, mergeable: true },
    ],
    outputs: [{ key: 'deleted', label: 'Deleted' }],
  },
  {
    kind: 'action',
    type: 'entity.transition_status',
    label: 'Change status',
    description: "Move a record to a status through its state machine.",
    icon: 'ArrowLeftRight',
    category: 'Actions',
    destructive: true,
    fields: [
      { key: 'entityType', label: 'Entity', type: 'entity', required: true, entityFilter: 'status' },
      {
        key: 'recordId',
        label: 'Record',
        type: 'text',
        required: true,
        mergeable: true,
        placeholder: '{{ trigger.record.id }}',
      },
      { key: 'toStatus', label: 'Move to status', type: 'status', required: true },
    ],
    outputs: [
      { key: 'status', label: 'New status' },
      { key: 'recordId', label: 'Record id' },
    ],
  },
  {
    kind: 'action',
    type: 'entity.update',
    label: 'Update a record',
    description: 'Patch fields on a record of the chosen entity.',
    icon: 'PencilLine',
    category: 'Actions',
    destructive: true,
    fields: [
      { key: 'entityType', label: 'Entity', type: 'entity', required: true },
      {
        key: 'recordId',
        label: 'Record',
        type: 'text',
        required: true,
        mergeable: true,
        placeholder: '{{ trigger.record.id }}',
      },
      { key: 'assignments', label: 'Set fields', type: 'assignments', required: true },
    ],
    outputs: [{ key: 'recordId', label: 'Record id' }],
  },
  {
    kind: 'action',
    type: 'omnichannel.get_contact',
    label: 'Get Contact',
    description: 'Load a contact by id into the workflow context.',
    icon: 'UserRound',
    category: 'Actions',
    module: 'omnichannel',
    fields: [
      {
        key: 'contactId',
        label: 'Contact',
        type: 'text',
        required: true,
        mergeable: true,
        placeholder: '{{ trigger.contact.id }}',
      },
    ],
    outputs: [
      { key: 'id', label: 'Contact id' },
      { key: 'name', label: 'Name' },
      { key: 'phone', label: 'Phone' },
      { key: 'email', label: 'Email' },
      { key: 'workspaceId', label: 'Workspace id' },
      { key: 'statusId', label: 'Status id' },
      { key: 'status', label: 'Status' },
    ],
  },
  {
    kind: 'action',
    type: 'omnichannel.send_message',
    label: 'Send Message',
    description: 'Send a text reply into the triggering conversation.',
    icon: 'Send',
    category: 'Actions',
    module: 'omnichannel',
    fields: [
      {
        key: 'contactId',
        label: 'Contact',
        type: 'text',
        required: true,
        mergeable: true,
        placeholder: '{{ trigger.contact.id }}',
      },
      { key: 'message', label: 'Message', type: 'textarea', required: true, mergeable: true },
    ],
    outputs: [
      { key: 'messageId', label: 'Message id' },
      { key: 'status', label: 'Send status' },
    ],
  },
  {
    kind: 'action',
    type: 'ai_agent.run',
    label: 'AI Agent',
    description: 'Send content to an AI agent and capture structured output.',
    icon: 'Sparkles',
    category: 'Actions',
    fields: [
      { key: 'agentId', label: 'Agent', type: 'aiAgent', required: true },
      {
        key: 'instructions',
        label: 'Instructions',
        type: 'textarea',
        required: true,
        mergeable: true,
      },
      {
        key: 'inputText',
        label: 'Message',
        type: 'textarea',
        required: true,
        mergeable: true,
        placeholder: '{{ trigger.message.text }}',
      },
      { key: 'outputParams', label: 'Output parameters', type: 'outputSchema', required: true },
    ],
    // Dynamic - the drawer lists config.outputParams as nodes.<id>.<key>.
    outputs: [],
  },
];

/** The IF node (built-in - D8). One catalog row so the palette/createNode/node
 * card treat it uniformly; its config (the rule tree) renders specially. */
export const IF_CATALOG: IfCatalogEntry[] = [
  {
    kind: 'if',
    type: 'if',
    label: 'Condition',
    description: 'Branch the flow - matching runs take the true path.',
    icon: 'GitBranch',
    category: 'Logic',
    fields: [],
    outputs: [],
  },
];

const CATALOG: NodeCatalogEntry[] = [...TRIGGER_CATALOG, ...ACTION_CATALOG, ...IF_CATALOG];

export function catalogEntry(type: string): NodeCatalogEntry | undefined {
  return CATALOG.find((e) => e.type === type);
}

export function isTriggerType(type: string): boolean {
  return TRIGGER_CATALOG.some((e) => e.type === type);
}
