/**
 * Mock contact-list service (S0, plan 26). Two families of rows, so the
 * detail page's Conversation/Details tabs (which reuse the ALREADY-REAL A1
 * `conversation-service` unchanged, per plan §2 "no second way to mutate a
 * contact") behave correctly for at least a demonstrable subset:
 *
 * - 5 ANCHOR rows (`cnt-001`..`cnt-005`) mirror the dev-seed demo inbox
 *   (`seed_demo_conversations`, backend `modules/omnichannel/bootstrap.py`) -
 *   these ids are REAL contacts on the live backend, so opening one in the
 *   detail form's Details/Conversation tabs hits the real, already-working
 *   A1 endpoints and shows a genuine thread.
 * - ~20 SYNTHETIC rows (`mock-contact-###`) exist ONLY in this in-memory
 *   store, so the List can be tuned (25+ contacts spanning lifecycle stages /
 *   tags / channels / assignees) with no backend list endpoint yet (S1). Their
 *   Details/Conversation tabs 404 against the real backend (expected S0
 *   limitation - the real list endpoint lands in S1 and replaces this whole
 *   file's role).
 *
 * To keep pickers foolproof (only valid options) the synthetic rows' tags /
 * lifecycle stages / assignees / channels are drawn from the WORKSPACE'S REAL
 * registries (`contact-tag-service`, `contact-field-service`,
 * `status-engine-service` graph, `workspace-service` members, `channel-service`)
 * - all already real since A1/earlier plans - rather than invented ids that
 * would never resolve in any picker.
 */
import { ApiError } from '@/lib/api-client';
import { ExportPendingError } from '@/lib/service-errors';
import type {
  BulkAssignInput,
  BulkLifecycleInput,
  BulkResult,
  BulkTagsInput,
  ChannelType,
  ContactChannelRef,
  ContactExportRequest,
  ContactField,
  ContactListItem,
  ContactTag,
  ContactTagRef,
  CreateContactInput,
  WorkspaceMember,
} from '@/types/omnichannel';
import type { FilterGroup, ListQuery, ListResult } from '@/types/resource';
import { channelService } from './channel-service';
import { contactFieldService } from './contact-field-service';
import { contactSegmentService } from './contact-segment-service';
import { contactTagService } from './contact-tag-service';
import { statusEngineService } from './status-engine-service';
import { workspaceService } from './workspace-service';
import { delay, runQuery, type QueryAdapter } from './mock-query';
import type { ContactService } from './contact-service';

const CONTACT_ENTITY_TYPE = 'omnichannel_contact_lifecycle';

interface StageRef {
  id: string;
  key: string;
  label: string;
  color: string;
  isInitial: boolean;
  isTerminal: boolean;
  isArchived: boolean;
}

interface WorkspaceRefs {
  tags: ContactTag[];
  fields: ContactField[];
  stages: StageRef[];
  members: WorkspaceMember[];
  channels: { id: string; channelType: ChannelType; name: string }[];
}

function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}

// Workspace registries are already REAL (A1) - fetch once per workspace and
// reuse for every synthesis below so pickers only ever offer live options.
const refsCache = new Map<string, Promise<WorkspaceRefs>>();

function loadRefs(workspaceId: string): Promise<WorkspaceRefs> {
  let cached = refsCache.get(workspaceId);
  if (!cached) {
    cached = Promise.all([
      contactTagService.list(workspaceId).catch(() => []),
      contactFieldService.list(workspaceId).catch(() => []),
      statusEngineService.graph(CONTACT_ENTITY_TYPE, workspaceId).catch(() => null),
      workspaceService.getMembers(workspaceId).catch(() => []),
      channelService.listByWorkspace(workspaceId).catch(() => []),
    ]).then(([tags, fields, graph, members, channels]) => ({
      tags,
      fields,
      stages: (graph?.statuses ?? []).map((s) => ({
        id: s.id,
        key: s.key,
        label: s.label,
        color: s.color,
        isInitial: s.isInitial,
        isTerminal: s.isTerminal,
        isArchived: s.isArchived,
      })),
      members,
      channels: channels.map((c) => ({ id: c.id, channelType: c.channelType, name: c.name })),
    }));
    refsCache.set(workspaceId, cached);
  }
  return cached;
}

const SYN_FIRST = ['Aaliyah', 'Benny', 'Chandra', 'Denise', 'Erwin', 'Faridah', 'Gopal', 'Halim', 'Ines', 'Jaya',
  'Kelvin', 'Latifah', 'Melvin', 'Nurul', 'Oscar', 'Puteri', 'Qistina', 'Reza', 'Suresh', 'Tania'];
const SYN_LAST = ['Rashid', 'Yap', 'Muthu', 'Ismail', 'Choo', 'Balan', 'Zulkifli', 'Hassan', 'Foo', 'Nathan'];
const COMPANIES = ['Acme Sdn Bhd', 'Globex Trading', 'Initech KL', 'Umbrella Retail', 'Stark Logistics'];

function sampleCustomValue(field: ContactField, i: number): string | number | boolean | null {
  switch (field.type) {
    case 'list':
      return field.options && field.options.length ? field.options[i % field.options.length] : null;
    case 'checkbox':
      return i % 2 === 0;
    case 'number':
      return (i % 9) * 250;
    case 'url':
      return `https://example.com/contact-${i + 1}`;
    case 'email':
      return `contact${i + 1}@example.com`;
    case 'date':
      return new Date(Date.parse('2026-01-01T00:00:00Z') + i * 86_400_000 * 3).toISOString().slice(0, 10);
    case 'time':
      return `${String(9 + (i % 8)).padStart(2, '0')}:00`;
    default:
      return COMPANIES[i % COMPANIES.length];
  }
}

// Fixed epoch for the synthetic rows (deterministic, matches the house
// convention in user-service.mock.ts) - the 5 anchor rows below deliberately
// use "now" instead, since their id/thread lives on the real backend and its
// timestamps move with wall-clock time regardless of what this file renders.
const EPOCH = Date.parse('2026-08-01T09:00:00Z');
const DAY = 86_400_000;

const ANCHOR_SEED: { id: string; first: string; last: string; phone: string; priority: ContactListItem['priority']; hoursAgo: number }[] = [
  { id: 'cnt-001', first: 'Sarah', last: 'Chen', phone: '+601234 56789', priority: 'HIGH', hoursAgo: 0.1 },
  { id: 'cnt-002', first: 'Marcus', last: 'Wong', phone: '+601688 82211', priority: 'MEDIUM', hoursAgo: 27 },
  { id: 'cnt-003', first: 'Priya', last: 'Raj', phone: '+601720 20303', priority: 'URGENT', hoursAgo: 0.5 },
  { id: 'cnt-004', first: 'Daniel', last: 'Lee', phone: '+601155 57788', priority: 'LOW', hoursAgo: 21 },
  { id: 'cnt-005', first: 'Aisha', last: 'Abdullah', phone: '+601944 49090', priority: 'MEDIUM', hoursAgo: 63 },
];

function anchorChannel(refs: WorkspaceRefs): ContactChannelRef[] {
  const demo = refs.channels.find((c) => c.id === 'chn-demo') ?? refs.channels[0];
  return demo ? [{ channelId: demo.id, channelType: demo.channelType, name: demo.name }] : [];
}

function synthChannel(refs: WorkspaceRefs, i: number): ContactChannelRef[] {
  if (refs.channels.length === 0) return [];
  // Every 6th synthetic contact has never messaged in - an empty channels[]
  // (AC-CTM-19 - never a defaulted channel type).
  if (i % 6 === 5) return [];
  const c = refs.channels[i % refs.channels.length];
  return [{ channelId: c.id, channelType: c.channelType, name: c.name }];
}

function stageFor(refs: WorkspaceRefs, i: number): ContactListItem['lifecycle'] {
  if (refs.stages.length === 0) return null;
  const s = refs.stages[i % refs.stages.length];
  return { statusId: s.id, key: s.key, label: s.label, color: s.color, isWon: s.isTerminal, isLost: s.isArchived };
}

function initialStageOf(refs: WorkspaceRefs): ContactListItem['lifecycle'] {
  const initial = refs.stages.find((s) => s.isInitial) ?? refs.stages[0];
  if (!initial) return null;
  return {
    statusId: initial.id,
    key: initial.key,
    label: initial.label,
    color: initial.color,
    isWon: initial.isTerminal,
    isLost: initial.isArchived,
  };
}

function tagsFor(refs: WorkspaceRefs, i: number): ContactTagRef[] {
  if (refs.tags.length === 0) return [];
  const count = i % 4; // 0-3 tags, foolproof spread
  const out: ContactTagRef[] = [];
  for (let n = 0; n < count; n++) {
    const t = refs.tags[(i + n) % refs.tags.length];
    if (!out.some((x) => x.id === t.id)) out.push({ id: t.id, name: t.name, emoji: t.emoji, color: t.color });
  }
  return out;
}

function assigneeFor(refs: WorkspaceRefs, i: number): { id: string | null; name: string | null } {
  if (refs.members.length === 0 || i % 5 === 4) return { id: null, name: null }; // some unassigned
  const m = refs.members[i % refs.members.length];
  return { id: m.userId, name: m.name };
}

function customFieldsFor(refs: WorkspaceRefs, i: number): Record<string, string | number | boolean | null> {
  const out: Record<string, string | number | boolean | null> = {};
  for (const f of refs.fields) out[f.key] = sampleCustomValue(f, i);
  return out;
}

function buildAnchorRows(workspaceId: string, refs: WorkspaceRefs): ContactListItem[] {
  const now = Date.now();
  const initial = initialStageOf(refs);
  return ANCHOR_SEED.map((a) => {
    const lastAt = new Date(now - a.hoursAgo * 60 * 60 * 1000).toISOString();
    return {
      id: a.id,
      tenantId: 'default',
      workspaceId,
      name: `${a.first} ${a.last}`,
      firstName: a.first,
      lastName: a.last,
      phone: a.phone,
      email: null,
      language: null,
      countryCode: null,
      avatarUrl: null,
      assignedUserId: null,
      assignedUserName: null,
      status: 'OPEN',
      priority: a.priority,
      channelId: anchorChannel(refs)[0]?.channelId ?? null,
      channelType: anchorChannel(refs)[0]?.channelType ?? 'WHATSAPP',
      cswExpiresAt: new Date(now + 20 * 60 * 60 * 1000).toISOString(),
      lastIncomingMessageAt: lastAt,
      lastMessageAt: lastAt,
      lastMessagePreview: 'Real demo thread - open Conversation to view it.',
      unreadCount: 0,
      customFields: {},
      tags: [],
      lifecycle: initial,
      createdAt: lastAt,
      channels: anchorChannel(refs),
    } satisfies ContactListItem;
  });
}

function buildSyntheticRows(workspaceId: string, refs: WorkspaceRefs, count: number): ContactListItem[] {
  return Array.from({ length: count }, (_, i) => {
    const first = SYN_FIRST[i % SYN_FIRST.length];
    const last = SYN_LAST[i % SYN_LAST.length];
    const createdAt = new Date(EPOCH - (i + 1) * DAY * 2).toISOString();
    const hasMessaged = i % 6 !== 5;
    const lastMessageAt = hasMessaged ? new Date(EPOCH - (i + 1) * DAY * 0.7).toISOString() : null;
    const assignee = assigneeFor(refs, i);
    const channels = synthChannel(refs, i);
    return {
      id: `mock-contact-${String(i + 1).padStart(3, '0')}`,
      tenantId: 'default',
      workspaceId,
      name: `${first} ${last}`,
      firstName: first,
      lastName: last,
      phone: `+60 1${(i % 9) + 1}-${String(1000 + i * 37).slice(0, 3)} ${String(2000 + i * 53).slice(0, 4)}`,
      email: i % 3 === 0 ? `${first.toLowerCase()}.${last.toLowerCase()}@example.com` : null,
      language: i % 4 === 0 ? 'en' : i % 4 === 1 ? 'zh-Hans' : null,
      countryCode: i % 3 === 0 ? 'MY' : null,
      avatarUrl: null,
      assignedUserId: assignee.id,
      assignedUserName: assignee.name,
      status: i % 7 === 0 ? 'CLOSED' : i % 5 === 0 ? 'SNOOZED' : 'OPEN',
      priority: (['LOW', 'MEDIUM', 'HIGH', 'URGENT'] as const)[i % 4],
      channelId: channels[0]?.channelId ?? null,
      channelType: channels[0]?.channelType ?? 'WHATSAPP',
      cswExpiresAt: hasMessaged && i % 2 === 0 ? new Date(EPOCH + DAY).toISOString() : null,
      lastIncomingMessageAt: lastMessageAt,
      lastMessageAt,
      lastMessagePreview: hasMessaged ? 'Synthetic S0 row - Conversation is not backed yet (S1).' : null,
      unreadCount: i % 4 === 0 ? (i % 3) + 1 : 0,
      customFields: customFieldsFor(refs, i),
      tags: tagsFor(refs, i),
      lifecycle: stageFor(refs, i),
      createdAt,
      channels,
    } satisfies ContactListItem;
  });
}

const contactsByWorkspace = new Map<string, ContactListItem[]>();

async function ensureContacts(workspaceId: string): Promise<ContactListItem[]> {
  const existing = contactsByWorkspace.get(workspaceId);
  if (existing) return existing;
  const refs = await loadRefs(workspaceId);
  const rows = [...buildAnchorRows(workspaceId, refs), ...buildSyntheticRows(workspaceId, refs, 22)];
  contactsByWorkspace.set(workspaceId, rows);
  return rows;
}

function digitsOf(phone: string): string {
  return phone.replace(/\D/g, '');
}

function combineFilters(a: FilterGroup | null | undefined, b: FilterGroup | null | undefined): FilterGroup | null {
  const groups = [a, b].filter((g): g is FilterGroup => !!g && g.rules.length > 0);
  if (groups.length === 0) return null;
  if (groups.length === 1) return groups[0];
  return { kind: 'group', combinator: 'and', rules: groups };
}

async function resolveSegmentFilter(workspaceId: string, segment: string | null | undefined): Promise<FilterGroup | null> {
  if (!segment || segment === 'all') return null;
  const segments = await contactSegmentService.list(workspaceId).catch(() => []);
  return segments.find((s) => s.id === segment)?.filter ?? null;
}

const adapter: QueryAdapter<ContactListItem> = {
  searchFields: ['name', 'phone', 'email'],
  getField(row, field) {
    if (field.startsWith('customFields.')) {
      const key = field.slice('customFields.'.length);
      return row.customFields[key] ?? null;
    }
    switch (field) {
      case 'name':
        return row.name;
      case 'firstName':
        return row.firstName;
      case 'lastName':
        return row.lastName;
      case 'phone':
        return row.phone;
      case 'email':
        return row.email;
      case 'language':
        return row.language;
      case 'countryCode':
        return row.countryCode;
      case 'priority':
        return row.priority;
      case 'assignee':
        return row.assignedUserId ?? 'unassigned';
      case 'channelType':
        return row.channels.map((c) => c.channelType);
      case 'lifecycle':
        return row.lifecycle?.key ?? null;
      case 'tags':
        return row.tags.map((t) => t.id);
      case 'lastMessageAt':
        return row.lastMessageAt;
      case 'createdAt':
        return row.createdAt;
      default:
        return null;
    }
  },
};

function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

function columnValue(row: ContactListItem, colId: string): string {
  switch (colId) {
    case 'id':
      return row.id;
    case 'name':
      return row.name;
    case 'phone':
      return row.phone ?? '';
    case 'email':
      return row.email ?? '';
    case 'lifecycle':
      return row.lifecycle?.label ?? '';
    case 'tags':
      // `,` to match the backend export (tags round-trip through the importer,
      // which splits on `,` - keep both sides on the same delimiter).
      return row.tags.map((t) => t.name).join(',');
    case 'assignee':
      return row.assignedUserName ?? '';
    case 'channel':
      return row.channels.map((c) => c.name).join('; ');
    case 'lastMessageAt':
      return row.lastMessageAt ?? '';
    case 'createdAt':
      return row.createdAt;
    default:
      return '';
  }
}

let createSeq = 1;

export const mockContactService: ContactService = {
  async list(workspaceId, query) {
    const rows = await ensureContacts(workspaceId);
    const segmentFilter = await resolveSegmentFilter(workspaceId, query.segment);
    const effective: ListQuery = { ...query, filter: combineFilters(segmentFilter, query.filter) };
    return delay(runQuery(rows, effective, adapter), 300);
  },

  async getAt(workspaceId, query, index) {
    const rows = await ensureContacts(workspaceId);
    const segmentFilter = await resolveSegmentFilter(workspaceId, query.segment);
    const effective: ListQuery = {
      ...query,
      filter: combineFilters(segmentFilter, query.filter),
      page: 0,
      pageSize: Math.max(rows.length, 1),
    };
    const full: ListResult<ContactListItem> = runQuery(rows, effective, adapter);
    return delay({ contact: full.data[index] ?? null, total: full.total }, 200);
  },

  async get(workspaceId, contactId) {
    const rows = await ensureContacts(workspaceId);
    const found = rows.find((r) => r.id === contactId);
    if (!found) throw new ApiError('Contact not found.', 404, null, null);
    return delay(found, 200);
  },

  async create(workspaceId, input: CreateContactInput) {
    const rows = await ensureContacts(workspaceId);
    const refs = await loadRefs(workspaceId);

    const errors: Record<string, string> = {};
    const phone = input.phone?.trim();
    if (!phone) errors.phone = 'Phone is required.';
    else if (rows.some((r) => r.phone && digitsOf(r.phone) === digitsOf(phone))) {
      errors.phone = 'A contact with this phone already exists in this workspace.';
    }
    if (input.tagIds?.some((id) => !refs.tags.some((t) => t.id === id))) {
      errors.tagIds = 'One or more tags do not belong to this workspace.';
    }
    if (Object.keys(errors).length) throw fieldErrorsError('Please fix the highlighted fields.', errors);

    const lifecycle = input.lifecycleStatusId
      ? (() => {
          const s = refs.stages.find((x) => x.id === input.lifecycleStatusId);
          return s
            ? { statusId: s.id, key: s.key, label: s.label, color: s.color, isWon: s.isTerminal, isLost: s.isArchived }
            : initialStageOf(refs);
        })()
      : initialStageOf(refs);

    const now = new Date().toISOString();
    const created: ContactListItem = {
      id: `mock-contact-new-${createSeq++}`,
      tenantId: 'default',
      workspaceId,
      name: `${input.firstName ?? ''} ${input.lastName ?? ''}`.trim() || phone!,
      firstName: input.firstName ?? null,
      lastName: input.lastName ?? null,
      phone: phone!,
      email: input.email ?? null,
      language: input.language ?? null,
      countryCode: input.countryCode ?? null,
      avatarUrl: null,
      assignedUserId: null,
      assignedUserName: null,
      status: 'OPEN',
      priority: 'MEDIUM',
      channelId: null,
      channelType: 'WHATSAPP',
      cswExpiresAt: null,
      lastIncomingMessageAt: null,
      lastMessageAt: null,
      lastMessagePreview: null,
      unreadCount: 0,
      customFields: input.customFields ?? {},
      tags: (input.tagIds ?? []).map((id) => {
        const t = refs.tags.find((x) => x.id === id)!;
        return { id: t.id, name: t.name, emoji: t.emoji, color: t.color };
      }),
      lifecycle,
      createdAt: now,
      channels: [],
    };
    rows.unshift(created);
    return delay(created, 350);
  },

  async bulkAssign(workspaceId, input: BulkAssignInput) {
    const rows = await ensureContacts(workspaceId);
    const refs = await loadRefs(workspaceId);
    const assigneeName = input.assigneeUserId
      ? (refs.members.find((m) => m.userId === input.assigneeUserId)?.name ?? null)
      : null;
    const result: BulkResult = { ok: [], failed: [] };
    for (const id of input.ids) {
      const idx = rows.findIndex((r) => r.id === id);
      if (idx === -1) {
        result.failed.push({ id, error: 'Contact not found.' });
        continue;
      }
      rows[idx] = { ...rows[idx], assignedUserId: input.assigneeUserId, assignedUserName: assigneeName };
      result.ok.push(id);
    }
    return delay(result, 500);
  },

  async bulkTags(workspaceId, input: BulkTagsInput) {
    const rows = await ensureContacts(workspaceId);
    const refs = await loadRefs(workspaceId);
    const unknown = input.tagIds.filter((id) => !refs.tags.some((t) => t.id === id));
    if (unknown.length) {
      throw fieldErrorsError('One or more tags do not belong to this workspace.', {
        tagIds: 'One or more tags do not belong to this workspace.',
      });
    }
    const result: BulkResult = { ok: [], failed: [] };
    for (const id of input.ids) {
      const idx = rows.findIndex((r) => r.id === id);
      if (idx === -1) {
        result.failed.push({ id, error: 'Contact not found.' });
        continue;
      }
      const currentIds = rows[idx].tags.map((t) => t.id);
      const nextIds =
        input.mode === 'add'
          ? Array.from(new Set([...currentIds, ...input.tagIds]))
          : currentIds.filter((tid) => !input.tagIds.includes(tid));
      rows[idx] = {
        ...rows[idx],
        tags: nextIds.map((tid) => {
          const t = refs.tags.find((x) => x.id === tid)!;
          return { id: t.id, name: t.name, emoji: t.emoji, color: t.color };
        }),
      };
      result.ok.push(id);
    }
    return delay(result, 500);
  },

  async bulkLifecycle(workspaceId, input: BulkLifecycleInput) {
    const rows = await ensureContacts(workspaceId);
    const refs = await loadRefs(workspaceId);
    const target = refs.stages.find((s) => s.id === input.toStatusId);
    if (!target) {
      throw fieldErrorsError('Unknown lifecycle stage.', { toStatusId: 'Unknown lifecycle stage.' });
    }
    const result: BulkResult = { ok: [], failed: [] };
    for (const id of input.ids) {
      const idx = rows.findIndex((r) => r.id === id);
      if (idx === -1) {
        result.failed.push({ id, error: 'Contact not found.' });
        continue;
      }
      const current = rows[idx].lifecycle;
      // Deterministic partial-failure demo (AC-CTM-31/-09): a terminal
      // ("won") stage has no outgoing edge, mirroring the real machine.
      if (current?.isWon && current.statusId !== target.id) {
        result.failed.push({ id, error: `No move from ${current.label}.` });
        continue;
      }
      rows[idx] = {
        ...rows[idx],
        lifecycle: {
          statusId: target.id,
          key: target.key,
          label: target.label,
          color: target.color,
          isWon: target.isTerminal,
          isLost: target.isArchived,
        },
      };
      result.ok.push(id);
    }
    return delay(result, 600);
  },

  async exportContacts(workspaceId, req: ContactExportRequest) {
    const rows = await ensureContacts(workspaceId);
    const segmentFilter = await resolveSegmentFilter(workspaceId, req.segment);
    const query: ListQuery = {
      page: 0,
      pageSize: Math.max(rows.length, 1),
      search: req.search,
      sort: req.sortBy ? { id: req.sortBy, desc: req.sortDir === 'desc' } : undefined,
      filter: combineFilters(segmentFilter, req.filter ?? null),
    };
    const matched = runQuery(rows, query, adapter).data;
    const selected = req.ids && req.ids.length ? matched.filter((r) => req.ids!.includes(r.id)) : matched;

    // D-A2-6a: an unfiltered "export everything" run demonstrates the
    // wait-window -> Jobs fallback (never a silent failure); a bounded
    // selection (or a filtered/segmented query) finishes inside the window.
    const jobId = `job-mock-${Date.now()}`;
    if (!req.ids && selected.length > 15) {
      await delay(undefined, 1400);
      throw new ExportPendingError('The export is still running - it will finish in Jobs.', jobId);
    }

    await delay(undefined, 400 + selected.length * 20);
    const header = req.columns.join(',');
    const body = selected.map((r) => req.columns.map((c) => csvEscape(columnValue(r, c))).join(',')).join('\n');
    return `${header}\n${body}`;
  },
};

/** Reset mock state (fresh browser session / between tests). */
export function __mockResetContacts(): void {
  contactsByWorkspace.clear();
  refsCache.clear();
  createSeq = 1;
}
