/**
 * Mock broadcast service (S0, plan 29). Single-workspace in-memory store -
 * six broadcasts spanning every `BroadcastStatus`, one (`Order confirmations`,
 * SENDING) carrying 40 recipients in mixed states so the Recipients table has
 * something real to filter/search. Mirrors the eventual backend contract
 * (§5.1 of the plan): audience is CONFIGURATION only until `send()` snapshots
 * it into recipient rows (D-A4-2); a claimed-but-unsent recipient never
 * double-sends (D-A4-8, mirrored here as "advance queued -> sent once").
 *
 * `audiencePreview` composes the REAL `conversationService.listThreads` +
 * the REAL `contactSegmentService` (A2, merged plan 26 - backend-wired
 * segments) with the shared `evalGroup` filter evaluator - so the count
 * shown while building a broadcast reflects the actual seeded demo contacts
 * AND a segment saved from the real Contacts list resolves correctly (only
 * `broadcasts` itself is mocked in S0).
 */
import { ApiError } from '@/lib/api-client';
import type {
  Broadcast,
  BroadcastAudience,
  BroadcastBindings,
  BroadcastCounts,
  BroadcastRecipient,
  BroadcastRecipientState,
  BroadcastStatus,
  ConversationThread,
  CreateBroadcastInput,
  UpdateBroadcastInput,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import { conversationService } from './conversation-service';
import { channelService } from './channel-service';
import { contactSegmentService } from './contact-segment-service';
import { delay, evalGroup, runQuery, type QueryAdapter } from './mock-query';

const STATUS_LABELS: Record<BroadcastStatus, string> = {
  DRAFT: 'Draft',
  SCHEDULED: 'Scheduled',
  SENDING: 'Sending',
  SENT: 'Sent',
  CANCELLED: 'Cancelled',
  FAILED: 'Failed',
};

function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}
function conflictError(reason: string, message: string): ApiError {
  return new ApiError(message, 409, null, { reason });
}

let idSeq = 1;
const nextId = () => `bcst-${String(idSeq++).padStart(3, '0')}`;
let recipientSeq = 1;
const nextRecipientId = () => `bcrec-${String(recipientSeq++).padStart(4, '0')}`;

const NOW = Date.now();
const iso = (msAgo: number) => new Date(NOW - msAgo).toISOString();
const HOUR = 3_600_000;
const DAY = 86_400_000;

function zeroCounts(): BroadcastCounts {
  return { total: 0, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 };
}

function countsFromRecipients(recipients: BroadcastRecipient[]): BroadcastCounts {
  const c = zeroCounts();
  c.total = recipients.length;
  for (const r of recipients) {
    if (r.state === 'sent') c.sent++;
    else if (r.state === 'delivered') c.delivered++;
    else if (r.state === 'read') c.read++;
    else if (r.state === 'failed') c.failed++;
    else if (r.state === 'skipped') c.skipped++;
  }
  return c;
}

function makeRecipient(
  n: number,
  broadcastId: string,
  state: BroadcastRecipientState,
  extra: Partial<BroadcastRecipient> = {},
): BroadcastRecipient {
  return {
    id: nextRecipientId(),
    contactId: `cnt-${broadcastId}-${String(n).padStart(2, '0')}`,
    contactName: `Recipient ${n}`,
    phone: `+1555${String(1000 + n).slice(-4)}`,
    state,
    attemptedAt: state === 'queued' ? null : iso((40 - n) * 60_000),
    ...extra,
  };
}

interface BroadcastRow extends Broadcast {
  /** Wall-clock bookkeeping for the SENDING demo row's incremental advance
   *  (never persisted server-side - a pure mock-timer convenience). */
  _lastTick?: number;
}

const recipientsStore = new Map<string, BroadcastRecipient[]>();

function bindings(body: number, header = 0, buttons = 0): BroadcastBindings {
  const mk = (n: number, prefix: string): BroadcastBindings['body'] =>
    Array.from({ length: n }, (_, i) =>
      i === 0
        ? { source: 'contactField', field: 'firstName', fallback: 'there' }
        : { source: 'static', text: `${prefix} value ${i + 1}` },
    );
  return { header: mk(header, 'Header'), body: mk(body, 'Body'), buttons: mk(buttons, 'Button') };
}

function seed(): { rows: BroadcastRow[]; recipients: Map<string, BroadcastRecipient[]> } {
  idSeq = 1;
  recipientSeq = 1;
  const rows: BroadcastRow[] = [];
  const recipients = new Map<string, BroadcastRecipient[]>();

  // 1. DRAFT
  {
    const id = nextId();
    rows.push({
      id,
      workspaceId: 'wsp-001',
      name: 'Welcome series',
      labels: ['onboarding'],
      channelId: 'chn-demo',
      channelName: 'Demo WhatsApp (sandbox)',
      audience: { kind: 'segment', segmentId: 'seg-1', segmentName: 'Urgent & high priority' },
      templateId: 'tpl-001',
      templateName: 'booking_update',
      templateLanguage: 'en_US',
      bindings: bindings(2),
      status: 'DRAFT',
      statusLabel: STATUS_LABELS.DRAFT,
      scheduledAt: null,
      startedAt: null,
      finishedAt: null,
      counts: zeroCounts(),
      jobId: null,
      error: null,
      createdByUserId: 'usr-001',
      createdByName: 'Aaron Tan',
      createdAt: iso(2 * DAY),
      updatedAt: iso(2 * DAY),
    });
    recipients.set(id, []);
  }

  // 2. SCHEDULED
  {
    const id = nextId();
    rows.push({
      id,
      workspaceId: 'wsp-001',
      name: 'Weekend promo',
      labels: ['promo'],
      channelId: 'chn-demo',
      channelName: 'Demo WhatsApp (sandbox)',
      audience: {
        kind: 'filter',
        filter: {
          kind: 'group',
          combinator: 'and',
          rules: [{ kind: 'condition', field: 'priority', operator: 'in', value: ['HIGH', 'URGENT'] }],
        },
      },
      templateId: 'tpl-001',
      templateName: 'booking_update',
      templateLanguage: 'en_US',
      bindings: bindings(2),
      status: 'SCHEDULED',
      statusLabel: STATUS_LABELS.SCHEDULED,
      scheduledAt: iso(-2 * DAY), // 2 days in the future
      startedAt: null,
      finishedAt: null,
      counts: zeroCounts(),
      jobId: null,
      error: null,
      createdByUserId: 'usr-002',
      createdByName: 'Bella Lim',
      createdAt: iso(DAY),
      updatedAt: iso(DAY),
    });
    recipients.set(id, []);
  }

  // 3. SENDING - 40 recipients, mixed states, advances on each read.
  {
    const id = nextId();
    const recs: BroadcastRecipient[] = [];
    for (let n = 1; n <= 40; n++) {
      if (n <= 4) recs.push(makeRecipient(n, id, 'read'));
      else if (n <= 8) recs.push(makeRecipient(n, id, 'delivered'));
      else if (n <= 14) recs.push(makeRecipient(n, id, 'sent'));
      else if (n === 15) recs.push(makeRecipient(n, id, 'skipped', { skipReason: 'no_identity' }));
      else recs.push(makeRecipient(n, id, 'queued', { attemptedAt: null }));
    }
    recipients.set(id, recs);
    rows.push({
      id,
      workspaceId: 'wsp-001',
      name: 'Order confirmations',
      labels: ['transactional'],
      channelId: 'chn-demo',
      channelName: 'Demo WhatsApp (sandbox)',
      audience: { kind: 'contacts', contactIds: recs.map((r) => r.contactId) },
      templateId: 'tpl-001',
      templateName: 'booking_update',
      templateLanguage: 'en_US',
      bindings: bindings(2),
      status: 'SENDING',
      statusLabel: STATUS_LABELS.SENDING,
      scheduledAt: null,
      startedAt: iso(10 * 60_000),
      finishedAt: null,
      counts: countsFromRecipients(recs),
      jobId: 'job-mock-003',
      error: null,
      createdByUserId: 'usr-001',
      createdByName: 'Aaron Tan',
      createdAt: iso(20 * 60_000),
      updatedAt: iso(60_000),
      _lastTick: NOW,
    });
  }

  // 4. SENT - with failures.
  {
    const id = nextId();
    const recs: BroadcastRecipient[] = [
      ...Array.from({ length: 6 }, (_, i) => makeRecipient(i + 1, id, 'read')),
      ...Array.from({ length: 2 }, (_, i) => makeRecipient(i + 7, id, 'delivered')),
      makeRecipient(9, id, 'failed', {
        errorCode: 'META_131026',
        errorText: 'Recipient number is not a valid WhatsApp user.',
      }),
      makeRecipient(10, id, 'failed', { errorCode: 'META_131047', errorText: 'Re-engagement window closed.' }),
      makeRecipient(11, id, 'skipped', { skipReason: 'no_identity' }),
      makeRecipient(12, id, 'skipped', { skipReason: 'duplicate' }),
    ];
    recipients.set(id, recs);
    rows.push({
      id,
      workspaceId: 'wsp-001',
      name: 'Flash sale blast',
      labels: ['promo', 'flash-sale'],
      channelId: 'chn-demo',
      channelName: 'Demo WhatsApp (sandbox)',
      audience: { kind: 'segment', segmentId: 'seg-2', segmentName: 'Unassigned' },
      templateId: 'tpl-001',
      templateName: 'booking_update',
      templateLanguage: 'en_US',
      bindings: bindings(2),
      status: 'SENT',
      statusLabel: STATUS_LABELS.SENT,
      scheduledAt: null,
      startedAt: iso(3 * DAY),
      finishedAt: iso(3 * DAY - 20 * 60_000),
      counts: countsFromRecipients(recs),
      jobId: 'job-mock-004',
      error: null,
      createdByUserId: 'usr-004',
      createdByName: 'Dahlia Rahman',
      createdAt: iso(3 * DAY + HOUR),
      updatedAt: iso(3 * DAY - 20 * 60_000),
    });
  }

  // 5. CANCELLED - mid-flight when cancelled.
  {
    const id = nextId();
    const recs: BroadcastRecipient[] = [
      ...Array.from({ length: 2 }, (_, i) => makeRecipient(i + 1, id, 'delivered')),
      makeRecipient(3, id, 'sent'),
      ...Array.from({ length: 6 }, (_, i) => makeRecipient(i + 4, id, 'skipped', { skipReason: 'cancelled' })),
    ];
    recipients.set(id, recs);
    rows.push({
      id,
      workspaceId: 'wsp-001',
      name: 'Abandoned cart nudge',
      labels: [],
      channelId: 'chn-demo',
      channelName: 'Demo WhatsApp (sandbox)',
      audience: { kind: 'segment', segmentId: 'seg-3', segmentName: 'No recent activity' },
      templateId: 'tpl-001',
      templateName: 'booking_update',
      templateLanguage: 'en_US',
      bindings: bindings(2),
      status: 'CANCELLED',
      statusLabel: STATUS_LABELS.CANCELLED,
      scheduledAt: null,
      startedAt: iso(5 * DAY),
      finishedAt: iso(5 * DAY - 5 * 60_000),
      counts: countsFromRecipients(recs),
      jobId: 'job-mock-005',
      error: null,
      createdByUserId: 'usr-002',
      createdByName: 'Bella Lim',
      createdAt: iso(5 * DAY + HOUR),
      updatedAt: iso(5 * DAY - 5 * 60_000),
    });
  }

  // 6. FAILED - preflight failure, zero recipients ever sent.
  {
    const id = nextId();
    recipients.set(id, []);
    rows.push({
      id,
      workspaceId: 'wsp-001',
      name: 'Price hike notice',
      labels: ['notice'],
      channelId: 'chn-demo',
      channelName: 'Demo WhatsApp (sandbox)',
      audience: { kind: 'contacts', contactIds: ['cnt-001', 'cnt-002'] },
      templateId: 'tpl-001',
      templateName: 'booking_update',
      templateLanguage: 'en_US',
      bindings: bindings(2),
      status: 'FAILED',
      statusLabel: STATUS_LABELS.FAILED,
      scheduledAt: null,
      startedAt: iso(6 * DAY),
      finishedAt: iso(6 * DAY - 60_000),
      counts: zeroCounts(),
      jobId: 'job-mock-006',
      error: 'Template is no longer approved on this channel.',
      createdByUserId: 'usr-005',
      createdByName: 'Elias Kaur',
      createdAt: iso(6 * DAY + HOUR),
      updatedAt: iso(6 * DAY - 60_000),
    });
  }

  return { rows, recipients };
}

function loadState(): void {
  const state = seed();
  rows = state.rows;
  recipientsStore.clear();
  state.recipients.forEach((recs, id) => recipientsStore.set(id, recs));
}

let rows: BroadcastRow[] = [];
loadState();

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetBroadcasts(): void {
  loadState();
}

/** Advance a SENDING row's queued recipients by wall-clock elapsed time - a
 *  pure "mock timer" (D-A4-8 mirrored: a recipient claimed once never sends
 *  twice, only queued -> sent -> delivered -> read moves forward). */
function tick(row: BroadcastRow): void {
  if (row.status !== 'SENDING') return;
  const recs = recipientsStore.get(row.id) ?? [];
  const last = row._lastTick ?? NOW;
  const elapsedSec = (Date.now() - last) / 1000;
  const steps = Math.floor(elapsedSec / 4); // one recipient step per ~4s of wall time
  if (steps <= 0) return;
  row._lastTick = Date.now();

  for (let i = 0; i < steps; i++) {
    // Promote read receipts forward before claiming new recipients (forward-only).
    const toRead = recs.find((r) => r.state === 'delivered');
    const toDeliver = recs.find((r) => r.state === 'sent');
    const queued = recs.find((r) => r.state === 'queued');
    if (toRead && Math.random() < 0.5) {
      toRead.state = 'read';
    } else if (toDeliver && Math.random() < 0.6) {
      toDeliver.state = 'delivered';
    } else if (queued) {
      const failed = Math.random() < 0.08;
      queued.attemptedAt = new Date().toISOString();
      queued.messageId = `msg-mock-${queued.id}`;
      queued.state = failed ? 'failed' : 'sent';
      if (failed) {
        queued.errorCode = 'META_131026';
        queued.errorText = 'Recipient number is not a valid WhatsApp user.';
      }
    } else {
      break;
    }
  }

  row.counts = countsFromRecipients(recs);
  row.updatedAt = new Date().toISOString();
  if (!recs.some((r) => r.state === 'queued')) {
    row.status = 'SENT';
    row.statusLabel = STATUS_LABELS.SENT;
    row.finishedAt = new Date().toISOString();
  }
}

function tickAll(): void {
  for (const r of rows) tick(r);
}

function toBroadcast(row: BroadcastRow): Broadcast {
  const { _lastTick, ...rest } = row;
  void _lastTick;
  return rest;
}

const adapter: QueryAdapter<BroadcastRow> = {
  searchFields: ['name'],
  getField: (row, field) => {
    switch (field) {
      case 'status':
        return row.status;
      case 'channel':
        return row.channelName;
      case 'scheduledAt':
        return row.scheduledAt;
      case 'createdAt':
        return row.createdAt;
      case 'createdBy':
        return row.createdByName;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function findOrThrow(id: string): BroadcastRow {
  const row = rows.find((r) => r.id === id);
  if (!row) throw new ApiError('Broadcast not found.', 404, null, null);
  return row;
}

function ensureAudienceValid(audience: BroadcastAudience): string | null {
  const has = {
    segment: !!audience.segmentId,
    filter: !!audience.filter && audience.filter.rules.length > 0,
    contacts: !!audience.contactIds && audience.contactIds.length > 0,
  };
  const providedCount = Object.values(has).filter(Boolean).length;
  if (providedCount !== 1) return 'Choose exactly one audience source.';
  if (audience.kind === 'segment' && !has.segment) return 'Choose a saved segment.';
  if (audience.kind === 'filter' && !has.filter) return 'Add at least one filter condition.';
  if (audience.kind === 'contacts' && !has.contacts) return 'Select at least one contact.';
  return null;
}

function validateCreate(input: CreateBroadcastInput): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!input.name.trim()) errors.name = 'Name is required.';
  else if (input.name.length > 200) errors.name = 'Name is too long (max 200 characters).';
  if (!input.channelId) errors.channelId = 'Choose a channel.';
  if (!input.templateId) errors.templateId = 'Choose a template.';
  const audienceError = ensureAudienceValid(input.audience);
  if (audienceError) errors.audience = audienceError;
  const allBindings = [...input.bindings.header, ...input.bindings.body, ...input.bindings.buttons];
  allBindings.forEach((b, i) => {
    if (b.source === 'static' && /\{\{|\}\}/.test(b.text)) {
      errors[`bindings.slot.${i}`] = 'Static text cannot contain template token syntax.';
    }
    if (b.source === 'contactField' && !b.fallback.trim()) {
      errors[`bindings.slot.${i}`] = 'A contact-field binding requires a fallback value.';
    }
  });
  if (input.scheduledAt && new Date(input.scheduledAt).getTime() < Date.now()) {
    errors.scheduledAt = 'Schedule a time in the future.';
  }
  return errors;
}

/** Resolve the contact identities behind an audience (S0 approximation - real
 *  SQL resolution lands with the S1 backend); used by both `audiencePreview`
 *  and `send()`'s snapshot. */
async function resolveAudienceContacts(
  workspaceId: string,
  audience: BroadcastAudience,
): Promise<ConversationThread[]> {
  const all = await conversationService.listThreads({ workspaceId });
  if (audience.kind === 'contacts') {
    const ids = new Set(audience.contactIds ?? []);
    return all.filter((c) => ids.has(c.id));
  }
  let filter = audience.filter;
  if (audience.kind === 'segment' && audience.segmentId) {
    const segments = await contactSegmentService.list(workspaceId);
    filter = segments.find((s) => s.id === audience.segmentId)?.filter;
  }
  if (!filter) return [];
  const group = filter;
  return all.filter((c) =>
    evalGroup(c, group, {
      searchFields: [],
      getField: (row, field) => (row as unknown as Record<string, unknown>)[field],
    }),
  );
}

/** Resolve the real channel name + template name/language behind the given
 *  ids (mirrors the backend's server-side denormalization, S1) - the mock
 *  reads the REAL channel/template services (only `broadcasts` itself is
 *  mocked in S0) so the list/detail never leak a raw id as a display name. */
async function resolveDisplayNames(
  workspaceId: string,
  channelId: string,
  templateId: string,
): Promise<{ channelName: string; templateName: string; templateLanguage: string }> {
  const [channels, templates] = await Promise.all([
    channelService.listByWorkspace(workspaceId).catch(() => []),
    conversationService.listTemplates(channelId).catch(() => []),
  ]);
  const channel = channels.find((c) => c.id === channelId);
  const template = templates.find((t) => t.id === templateId);
  return {
    channelName: channel?.name ?? channelId,
    templateName: template?.name ?? templateId,
    templateLanguage: template?.language ?? 'en_US',
  };
}

export interface BroadcastService {
  list(workspaceId: string, query: ListQuery): Promise<ListResult<Broadcast>>;
  get(workspaceId: string, id: string): Promise<Broadcast>;
  audiencePreview(workspaceId: string, audience: BroadcastAudience): Promise<{ count: number }>;
  create(workspaceId: string, input: CreateBroadcastInput): Promise<Broadcast>;
  update(workspaceId: string, id: string, input: UpdateBroadcastInput): Promise<Broadcast>;
  remove(workspaceId: string, id: string): Promise<void>;
  duplicate(workspaceId: string, id: string): Promise<Broadcast>;
  send(workspaceId: string, id: string, scheduledAt?: string | null): Promise<Broadcast>;
  cancel(workspaceId: string, id: string): Promise<Broadcast>;
  testSend(workspaceId: string, id: string, contactId: string): Promise<{ messageId: string }>;
  recipients(
    workspaceId: string,
    id: string,
    query: { page: number; pageSize: number; state?: string; search?: string },
  ): Promise<ListResult<BroadcastRecipient>>;
}

export const mockBroadcastService: BroadcastService = {
  async list(_workspaceId, query) {
    void _workspaceId;
    tickAll();
    let filteredBySegment = rows;
    if (query.segment && query.segment !== 'all') {
      filteredBySegment = rows.filter((r) => r.status === query.segment);
    }
    const result = runQuery(filteredBySegment, { ...query, segment: undefined }, adapter);
    return delay({ ...result, data: result.data.map(toBroadcast) }, 250);
  },

  async get(_workspaceId, id) {
    void _workspaceId;
    tickAll();
    const row = findOrThrow(id);
    return delay(toBroadcast(row), 200);
  },

  async audiencePreview(workspaceId, audience) {
    const audienceError = ensureAudienceValid(audience);
    if (audienceError) return delay({ count: 0 }, 150);
    const contacts = await resolveAudienceContacts(workspaceId, audience);
    return delay({ count: contacts.length }, 200);
  },

  async create(workspaceId, input) {
    const errors = validateCreate(input);
    if (Object.keys(errors).length) throw fieldErrorsError('Please fix the highlighted fields.', errors);
    const id = nextId();
    const names = await resolveDisplayNames(workspaceId, input.channelId, input.templateId);
    const row: BroadcastRow = {
      id,
      workspaceId,
      name: input.name.trim(),
      labels: input.labels ?? [],
      channelId: input.channelId,
      channelName: names.channelName,
      audience: input.audience,
      templateId: input.templateId,
      templateName: names.templateName,
      templateLanguage: names.templateLanguage,
      bindings: input.bindings,
      status: 'DRAFT',
      statusLabel: STATUS_LABELS.DRAFT,
      scheduledAt: null,
      startedAt: null,
      finishedAt: null,
      counts: zeroCounts(),
      jobId: null,
      error: null,
      createdByUserId: 'usr-001',
      createdByName: 'You',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    rows = [row, ...rows];
    recipientsStore.set(id, []);
    return delay(toBroadcast(row), 300);
  },

  async update(workspaceId, id, input) {
    const row = findOrThrow(id);
    if (row.status !== 'DRAFT' && !(row.status === 'SCHEDULED' && Object.keys(input).length === 1 && 'scheduledAt' in input)) {
      throw conflictError('broadcast_not_editable', 'Only a Draft broadcast can be edited.');
    }
    const channelOrTemplateChanged = !!input.channelId || !!input.templateId;
    if (input.name !== undefined || channelOrTemplateChanged || input.audience || input.bindings) {
      const merged: CreateBroadcastInput = {
        name: input.name ?? row.name,
        labels: input.labels ?? row.labels,
        channelId: input.channelId ?? row.channelId,
        audience: input.audience ?? row.audience,
        templateId: input.templateId ?? row.templateId,
        bindings: input.bindings ?? row.bindings,
        scheduledAt: input.scheduledAt ?? row.scheduledAt,
      };
      const errors = validateCreate(merged);
      if (Object.keys(errors).length) throw fieldErrorsError('Please fix the highlighted fields.', errors);
    }
    if (channelOrTemplateChanged) {
      const names = await resolveDisplayNames(workspaceId, input.channelId ?? row.channelId, input.templateId ?? row.templateId);
      Object.assign(row, names);
    }
    Object.assign(row, input, { updatedAt: new Date().toISOString() });
    return delay(toBroadcast(row), 300);
  },

  async remove(_workspaceId, id) {
    void _workspaceId;
    const row = findOrThrow(id);
    if (row.status !== 'DRAFT') throw conflictError('broadcast_not_editable', 'Only a Draft broadcast can be deleted.');
    rows = rows.filter((r) => r.id !== id);
    recipientsStore.delete(id);
    return delay(undefined, 200);
  },

  async duplicate(_workspaceId, id) {
    void _workspaceId;
    const row = findOrThrow(id);
    const newId = nextId();
    const existingNames = new Set(rows.map((r) => r.name));
    let name = `${row.name} (copy)`;
    let n = 2;
    while (existingNames.has(name)) name = `${row.name} (copy ${n++})`;
    const copy: BroadcastRow = {
      ...row,
      id: newId,
      name,
      status: 'DRAFT',
      statusLabel: STATUS_LABELS.DRAFT,
      scheduledAt: null,
      startedAt: null,
      finishedAt: null,
      counts: zeroCounts(),
      jobId: null,
      error: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    rows = [copy, ...rows];
    recipientsStore.set(newId, []);
    return delay(toBroadcast(copy), 300);
  },

  async send(workspaceId, id, scheduledAt) {
    const row = findOrThrow(id);
    if (row.status !== 'DRAFT' && row.status !== 'SCHEDULED') {
      throw conflictError('broadcast_already_sending', 'This broadcast cannot be sent again.');
    }
    if (scheduledAt) {
      const at = new Date(scheduledAt);
      if (at.getTime() < Date.now()) throw fieldErrorsError('Schedule a time in the future.', { scheduledAt: 'Schedule a time in the future.' });
      row.status = 'SCHEDULED';
      row.statusLabel = STATUS_LABELS.SCHEDULED;
      row.scheduledAt = scheduledAt;
      row.updatedAt = new Date().toISOString();
      return delay(toBroadcast(row), 300);
    }
    // Send now - snapshot the audience into recipients (D-A4-2).
    const contacts = await resolveAudienceContacts(workspaceId, row.audience);
    const recs: BroadcastRecipient[] = contacts.map((c, i) =>
      makeRecipient(i + 1, row.id, i === 0 ? 'sent' : 'queued', {
        contactId: c.id,
        contactName: c.name,
        phone: c.phone,
        attemptedAt: i === 0 ? new Date().toISOString() : null,
        messageId: i === 0 ? `msg-mock-${row.id}-0` : undefined,
      }),
    );
    recipientsStore.set(row.id, recs);
    row.status = 'SENDING';
    row.statusLabel = STATUS_LABELS.SENDING;
    row.scheduledAt = null;
    row.startedAt = new Date().toISOString();
    row.jobId = `job-mock-${row.id}`;
    row.counts = countsFromRecipients(recs);
    row._lastTick = Date.now();
    row.updatedAt = new Date().toISOString();
    if (recs.length === 0) {
      row.status = 'SENT';
      row.statusLabel = STATUS_LABELS.SENT;
      row.finishedAt = new Date().toISOString();
    }
    return delay(toBroadcast(row), 400);
  },

  async cancel(_workspaceId, id) {
    void _workspaceId;
    const row = findOrThrow(id);
    if (row.status !== 'SCHEDULED' && row.status !== 'SENDING') {
      throw conflictError('broadcast_not_cancellable', 'This broadcast can no longer be cancelled.');
    }
    const recs = recipientsStore.get(id) ?? [];
    for (const r of recs) {
      if (r.state === 'queued') {
        r.state = 'skipped';
        r.skipReason = 'cancelled';
      }
    }
    row.status = 'CANCELLED';
    row.statusLabel = STATUS_LABELS.CANCELLED;
    row.counts = countsFromRecipients(recs);
    row.finishedAt = new Date().toISOString();
    row.updatedAt = new Date().toISOString();
    return delay(toBroadcast(row), 300);
  },

  async testSend(_workspaceId, id, contactId) {
    void _workspaceId;
    findOrThrow(id);
    if (!contactId) throw fieldErrorsError('Choose a contact.', { contactId: 'Choose a contact.' });
    return delay({ messageId: `msg-mock-test-${Date.now()}` }, 350);
  },

  async recipients(_workspaceId, id, query) {
    void _workspaceId;
    tickAll();
    findOrThrow(id);
    let recs = recipientsStore.get(id) ?? [];
    if (query.state) recs = recs.filter((r) => r.state === query.state);
    if (query.search?.trim()) {
      const q = query.search.trim().toLowerCase();
      recs = recs.filter(
        (r) => r.contactName.toLowerCase().includes(q) || (r.phone ?? '').toLowerCase().includes(q),
      );
    }
    const total = recs.length;
    const start = query.page * query.pageSize;
    const data = recs.slice(start, start + query.pageSize);
    return delay({ data, total, page: query.page }, 200);
  },
};
