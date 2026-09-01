/**
 * PHASE 1 MOCK - in-memory quick replies (plan sprint-3/12). Retained for tests
 * + tunable frontend states; the shipped page binds the REAL service. Delete
 * once no longer referenced.
 */
import type { QuickReply } from '@/types/omnichannel';
import type {
  QuickReplyCreateInput,
  QuickReplyService,
  QuickReplyUpdateInput,
} from './quick-reply-service';

const store = new Map<string, QuickReply[]>();
let seq = 0;

function seed(): QuickReply[] {
  return [
    { id: 'qr-1', workspaceId: 'wsp-1', shortcut: '/hi', body: 'Hi! How can I help?' },
    { id: 'qr-2', workspaceId: 'wsp-1', shortcut: '/hours', body: 'We are open Mon-Fri 9-6.' },
  ];
}

function rowsFor(workspaceId: string): QuickReply[] {
  if (!store.has(workspaceId)) {
    store.set(
      workspaceId,
      seed().map((r) => ({ ...r, workspaceId })),
    );
  }
  return store.get(workspaceId)!;
}

function sortRows(rows: QuickReply[]): QuickReply[] {
  return [...rows].sort((a, b) => (a.shortcut ?? '~').localeCompare(b.shortcut ?? '~'));
}

export const mockQuickReplyService: QuickReplyService = {
  async list(workspaceId) {
    return sortRows(rowsFor(workspaceId));
  },
  async create(workspaceId, input: QuickReplyCreateInput) {
    const rows = rowsFor(workspaceId);
    const shortcut = input.shortcut?.trim() || null;
    if (shortcut && rows.some((r) => r.shortcut === shortcut)) {
      throw new Error('That shortcut is already in use.');
    }
    const row: QuickReply = {
      id: `qr-mock-${++seq}`,
      workspaceId,
      shortcut,
      body: input.body.trim(),
    };
    rows.push(row);
    return row;
  },
  async update(workspaceId, id, input: QuickReplyUpdateInput) {
    const rows = rowsFor(workspaceId);
    const row = rows.find((r) => r.id === id);
    if (!row) throw new Error('Quick reply not found.');
    if (input.shortcut !== undefined) {
      const shortcut = input.shortcut?.trim() || null;
      if (shortcut && rows.some((r) => r.id !== id && r.shortcut === shortcut)) {
        throw new Error('That shortcut is already in use.');
      }
      row.shortcut = shortcut;
    }
    if (input.body !== undefined) row.body = input.body.trim();
    return { ...row };
  },
  async remove(workspaceId, id) {
    const rows = rowsFor(workspaceId);
    const i = rows.findIndex((r) => r.id === id);
    if (i >= 0) rows.splice(i, 1);
  },
};

/** Test hook: reset the in-memory store between cases. */
export function __resetMockQuickReplies(): void {
  store.clear();
  seq = 0;
}
