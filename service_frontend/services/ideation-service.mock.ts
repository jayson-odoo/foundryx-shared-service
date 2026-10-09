/**
 * In-memory ideation MOCK service (issue #94, ideation round 2, plan section
 * 3.5) - `ideation-service.ts` names this file for a while ("Mock retained in
 * *.mock.ts for tests") but it never existed; every idea/board/list state was
 * exercised live against the real backend instead. Slice S1 (frontend-mock
 * before backend, per PRINCIPLES.md) builds it for real: a believable
 * statuses-engine stand-in (fixed status set + forward edges, matching the
 * shape `status_machine.fireable_edge_ids` returns) so the list, board and
 * form can be tuned end to end with no backend running, then bound behind the
 * ONE line in `ideation-service.ts`.
 *
 * Kept deliberately close to the eventual backend contract (D11 rank rules,
 * D1-D10 merge/unmerge semantics) so slice S5's swap to `ideation-service.real`
 * changes no caller.
 */
import type {
  Board,
  BoardColumn,
  Idea,
  IdeaClusterSuggestions,
  IdeaComment,
  IdeaRef,
  IdeaTransition,
  Product,
} from '@/types/ideation';
import type { IdeaCreateInput, IdeaService, IdeaExtendedOps } from './ideation-service';

interface StatusDef {
  id: string;
  key: string;
  label: string;
  color: string;
  isArchived: boolean;
  sortOrder: number;
}

/** The tenant's (mock) idea status tier - stand-in for the statuses engine.
 * `captured -> triaged -> linked -> building -> delivered -> closed` is the
 * main path; `rejected`/`duplicate`/`archived` are archived off-ramps. */
const STATUSES: StatusDef[] = [
  { id: 'idea-status-captured', key: 'captured', label: 'New', color: 'blue', isArchived: false, sortOrder: 1 },
  { id: 'idea-status-triaged', key: 'triaged', label: 'Triaged', color: 'amber', isArchived: false, sortOrder: 2 },
  { id: 'idea-status-linked', key: 'linked', label: 'Linked to BR', color: 'violet', isArchived: false, sortOrder: 3 },
  { id: 'idea-status-building', key: 'building', label: 'Building', color: 'indigo', isArchived: false, sortOrder: 4 },
  { id: 'idea-status-delivered', key: 'delivered', label: 'Delivered', color: 'emerald', isArchived: false, sortOrder: 5 },
  { id: 'idea-status-closed', key: 'closed', label: 'Closed', color: 'gray', isArchived: true, sortOrder: 6 },
  { id: 'idea-status-rejected', key: 'rejected', label: 'Rejected', color: 'rose', isArchived: true, sortOrder: 7 },
  { id: 'idea-status-duplicate', key: 'duplicate', label: 'Duplicate', color: 'gray', isArchived: true, sortOrder: 8 },
  { id: 'idea-status-archived', key: 'archived', label: 'Archived', color: 'gray', isArchived: true, sortOrder: 9 },
];

/** The main-path forward edge from each active status key. */
const FORWARD_KEY: Record<string, string> = {
  captured: 'triaged',
  triaged: 'linked',
  linked: 'building',
  building: 'delivered',
  delivered: 'closed',
};

const BOARD_STATUS_KEYS = ['captured', 'triaged', 'linked', 'building', 'delivered'];

function statusByKey(key: string): StatusDef {
  return STATUSES.find((s) => s.key === key) ?? STATUSES[0];
}
function statusById(id: string): StatusDef | undefined {
  return STATUSES.find((s) => s.id === id);
}

let seq = 1000;
function nextId(prefix: string): string {
  seq += 1;
  return `${prefix}-${seq}`;
}

const PRODUCTS: Product[] = [
  { id: 'prod-crm', name: 'Sorento CRM', kind: 'software', productDomainBase: null },
  { id: 'prod-pos', name: 'Retail POS', kind: 'software', productDomainBase: null },
];

interface MockIdeaRecord {
  idea: Idea;
  /** Internal merge bookkeeping - never serialized onto `Idea` directly. */
  mergedAt: string | null;
  /** Vote snapshot taken at merge time, so unmerge can give the exact counts
   * back (D4 - lossless unmerge) without modelling a full per-voter ledger. */
  preMergeVotes: { upvotes: number; downvotes: number } | null;
}

let records: MockIdeaRecord[] = [];
let comments: IdeaComment[] = [];

function seed() {
  records = [];
  // `idea-seed-*` ids - deliberately DISJOINT from `nextId('idea')`'s
  // `idea-<seq>` space, so a freshly captured idea in a live session (or a
  // test that captures several) never collides with a seeded row.
  const rows: Array<Partial<Idea> & { problem: string; productId: string; statusKey: string }> = [
    { id: 'idea-seed-1', productId: 'prod-crm', problem: 'Export orders to Excel', statusKey: 'captured', upvotes: 5, downvotes: 0, submitterName: 'Aisha Rahman', source: 'whatsapp' },
    { id: 'idea-seed-2', productId: 'prod-crm', problem: 'Bulk approve quotations', statusKey: 'triaged', upvotes: 3, downvotes: 0, submitterName: 'Wei Ming', source: 'whatsapp' },
    { id: 'idea-seed-3', productId: 'prod-pos', problem: 'Faster barcode scanning at checkout', statusKey: 'linked', upvotes: 8, downvotes: 0, submitterName: 'Farah Aziz', source: 'voice' },
    { id: 'idea-seed-4', productId: 'prod-pos', problem: 'Offline receipt printing', statusKey: 'building', upvotes: 2, downvotes: 0, submitterName: 'Operator', source: 'manual' },
    { id: 'idea-seed-5', productId: 'prod-crm', problem: 'Show promo price in red on price tags', statusKey: 'delivered', upvotes: 6, downvotes: 0, submitterName: 'Aisha Rahman', source: 'whatsapp' },
    { id: 'idea-seed-6', productId: 'prod-crm', problem: 'Duplicate customer records cleanup', statusKey: 'archived', upvotes: 1, downvotes: 0, submitterName: 'Wei Ming', source: 'whatsapp' },
  ];
  rows.forEach((r, i) => {
    const status = statusByKey(r.statusKey);
    const product = PRODUCTS.find((p) => p.id === r.productId)!;
    const idea: Idea = {
      id: r.id!,
      productId: product.id,
      productName: product.name,
      status: status.key,
      title: null,
      problem: r.problem,
      proposedSolution: null,
      impact: null,
      department: null,
      rawText: r.problem,
      source: r.source ?? 'manual',
      submitterName: r.submitterName ?? 'Operator',
      submitterTier: null,
      upvotes: r.upvotes ?? 0,
      downvotes: r.downvotes ?? 0,
      myVote: null,
      priority: i,
      attachments: [],
      createdAt: new Date(2026, 6, 10 + i).toISOString(),
      ideaNumber: `IDEA-${String(1000 + i + 1).padStart(4, '0')}`,
      isTest: false,
      mergedIntoId: null,
      mergedInto: null,
      mergedCount: 0,
    };
    records.push({ idea, mergedAt: null, preMergeVotes: null });
  });
}
seed();

function findRecord(id: string): MockIdeaRecord | undefined {
  return records.find((r) => r.idea.id === id);
}
function requireRecord(id: string): MockIdeaRecord {
  const rec = findRecord(id);
  if (!rec) throw new Error('Idea not found.');
  return rec;
}

/** Transitions fireable from `idea`'s current status - the mock stand-in for
 * `status_machine.fireable_edge_ids(..., always=True)` (AC-94-51). */
function transitionsFor(idea: Idea): IdeaTransition[] {
  const status = statusByKey(idea.status);
  if (status.isArchived) {
    const target = statusByKey('captured');
    return [
      {
        id: 'idea-tr-restore',
        label: 'Restore',
        toStatusId: target.id,
        toStatusLabel: target.label,
      },
    ];
  }
  const nextKey = FORWARD_KEY[status.key];
  if (!nextKey) return [];
  const target = statusByKey(nextKey);
  return [
    {
      id: `idea-tr-${status.key}-${nextKey}`,
      label: `Move to ${target.label}`,
      toStatusId: target.id,
      toStatusLabel: target.label,
    },
  ];
}

function advanceTransitionId(transitions: IdeaTransition[], idea: Idea): string | null {
  if (statusByKey(idea.status).isArchived) return null;
  return transitions[0]?.id ?? null;
}

/** Ranks (1-based, AC-94-41/42) computed per `(productId | tenant-wide, isTest)`
 * lane, over ACTIVE survivors only, ordered `priority asc, createdAt desc, id
 * desc` - never the raw stored `priority`. */
function rankMap(scope: { productId?: string; includeTest: boolean }): Map<string, number> {
  const lane = records
    .map((r) => r.idea)
    .filter((i) => !i.mergedIntoId)
    .filter((i) => !statusByKey(i.status).isArchived)
    .filter((i) => (scope.includeTest ? true : !i.isTest))
    .filter((i) => (scope.productId ? i.productId === scope.productId : true))
    .sort((a, b) => a.priority - b.priority || b.createdAt.localeCompare(a.createdAt) || b.id.localeCompare(a.id));
  const map = new Map<string, number>();
  lane.forEach((i, idx) => map.set(i.id, idx + 1));
  return map;
}

/** Assemble the wire-shaped `Idea` (status display + transitions + rank +
 * merge bookkeeping) from the stored record - called on every read so a
 * rename/reorder/merge is reflected immediately, never cached stale. */
function present(idea: Idea, ranks: Map<string, number>): Idea {
  const status = statusByKey(idea.status);
  const transitions = idea.mergedIntoId ? [] : transitionsFor(idea);
  const mergedCount = records.filter((r) => r.idea.mergedIntoId === idea.id).length;
  return {
    ...idea,
    statusId: status.id,
    statusLabel: status.label,
    statusColor: status.color,
    statusIsArchived: status.isArchived,
    transitions,
    advanceTransitionId: idea.mergedIntoId ? null : advanceTransitionId(transitions, idea),
    rank: idea.mergedIntoId || status.isArchived ? null : (ranks.get(idea.id) ?? null),
    mergedCount,
  };
}

function toRef(idea: Idea): IdeaRef {
  return { id: idea.id, ideaNumber: idea.ideaNumber ?? null, title: idea.title ?? idea.problem };
}

/** `filter` mirrors the real backend's `GET /ideation/ideas?filter=` scope
 * (AC-94-60): `'active'` (the server default) excludes archived statuses,
 * `'archived'` returns only them, `'all'` returns both - never a hardcoded
 * status key, always the engine trait `statusIsArchived`. */
function allPresented(includeTest: boolean, filter: 'active' | 'archived' | 'all' = 'active'): Idea[] {
  const ranks = rankMap({ includeTest });
  return records
    .filter((r) => !r.idea.mergedIntoId)
    .filter((r) => (includeTest ? true : !r.idea.isTest))
    .filter((r) => {
      if (filter === 'all') return true;
      const archived = statusByKey(r.idea.status).isArchived;
      return filter === 'archived' ? archived : !archived;
    })
    .map((r) => present(r.idea, ranks));
}

export const mockIdeationService: IdeaService & IdeaExtendedOps = {
  async listProducts(): Promise<Product[]> {
    return PRODUCTS.map((p) => ({ ...p }));
  },

  async listIdeas(opts?: { includeTest?: boolean; filter?: 'active' | 'archived' | 'all' }): Promise<Idea[]> {
    return allPresented(Boolean(opts?.includeTest), opts?.filter ?? 'active');
  },

  async getIdea(id: string): Promise<Idea> {
    const rec = requireRecord(id);
    const ranks = rankMap({ includeTest: true });
    const idea = present(rec.idea, ranks);
    if (rec.idea.mergedIntoId) {
      const survivor = findRecord(rec.idea.mergedIntoId);
      idea.mergedInto = survivor ? toRef(survivor.idea) : null;
    }
    return idea;
  },

  async createIdea(input: IdeaCreateInput): Promise<Idea> {
    const product = PRODUCTS.find((p) => p.id === input.productId);
    if (!product) throw new Error('Unknown product.');
    const active = records
      .map((r) => r.idea)
      .filter((i) => !i.mergedIntoId && !statusByKey(i.status).isArchived && i.productId === product.id);
    const maxPriority = active.reduce((m, i) => Math.max(m, i.priority), -1);
    const idea: Idea = {
      id: nextId('idea'),
      productId: product.id,
      productName: product.name,
      status: 'captured',
      title: null,
      problem: input.problem,
      proposedSolution: input.proposedSolution ?? null,
      impact: input.impact ?? null,
      department: input.department ?? null,
      rawText: input.rawText,
      source: 'manual',
      submitterName: 'Operator',
      submitterTier: null,
      upvotes: 0,
      downvotes: 0,
      myVote: null,
      priority: maxPriority + 1,
      attachments: [],
      createdAt: new Date().toISOString(),
      ideaNumber: `IDEA-${String(seq).padStart(4, '0')}`,
      isTest: false,
      mergedIntoId: null,
      mergedInto: null,
      mergedCount: 0,
    };
    records.push({ idea, mergedAt: null, preMergeVotes: null });
    return mockIdeationService.getIdea(idea.id);
  },

  async updateIdea(id: string, input: Partial<IdeaCreateInput>): Promise<Idea> {
    const rec = requireRecord(id);
    if (input.productId !== undefined) {
      const product = PRODUCTS.find((p) => p.id === input.productId);
      if (product) {
        rec.idea.productId = product.id;
        rec.idea.productName = product.name;
      }
    }
    if (input.problem !== undefined) rec.idea.problem = input.problem;
    if (input.proposedSolution !== undefined) rec.idea.proposedSolution = input.proposedSolution;
    if (input.impact !== undefined) rec.idea.impact = input.impact;
    if (input.department !== undefined) rec.idea.department = input.department;
    if (input.rawText !== undefined) rec.idea.rawText = input.rawText;
    return mockIdeationService.getIdea(id);
  },

  async setStatus(id: string, toStatusId: string): Promise<Idea> {
    const rec = requireRecord(id);
    if (rec.idea.mergedIntoId) {
      const survivor = findRecord(rec.idea.mergedIntoId);
      throw new Error(`Merged into ${survivor?.idea.ideaNumber ?? 'another idea'}.`);
    }
    // Accept either an engine status id (the normal path) or the legacy
    // lifecycle KEY (the deferred Archive handler's shape, AC-94-53).
    const target = statusById(toStatusId) ?? statusByKey(toStatusId);
    if (!target) throw new Error('Unknown status.');
    rec.idea.status = target.key;
    return mockIdeationService.getIdea(id);
  },

  async vote(id: string, dir: 'up'): Promise<Idea> {
    const rec = requireRecord(id);
    if (rec.idea.mergedIntoId) {
      const survivor = findRecord(rec.idea.mergedIntoId);
      throw new Error(`Merged into ${survivor?.idea.ideaNumber ?? 'another idea'}.`);
    }
    // Upvote only (plan 19): toggling the same vote clears it.
    void dir;
    if (rec.idea.myVote === 'up') {
      rec.idea.upvotes -= 1;
      rec.idea.myVote = null;
    } else {
      rec.idea.upvotes += 1;
      rec.idea.myVote = 'up';
    }
    return mockIdeationService.getIdea(id);
  },

  // Comments (plan 19, AC-19-25): flat, oldest first; one reply level; soft
  // delete with the placeholder / omission rule of the backend.
  async listComments(ideaId: string): Promise<IdeaComment[]> {
    requireRecord(ideaId);
    const rows = comments.filter((c) => c.ideaId === ideaId);
    const parentsWithLiveReplies = new Set(
      rows.filter((c) => !c.isDeleted && c.parentId).map((c) => c.parentId as string),
    );
    return rows
      .filter((c) => !c.isDeleted || (c.parentId === null && parentsWithLiveReplies.has(c.id)))
      .map((c) => ({ ...c }));
  },

  async addComment(ideaId: string, body: string, parentId?: string): Promise<IdeaComment> {
    const rec = requireRecord(ideaId);
    if (rec.idea.mergedIntoId) throw new Error('This idea was merged into another idea.');
    const text = body.trim();
    if (!text) throw new Error('Comment cannot be empty.');
    let topId: string | null = null;
    if (parentId) {
      const parent = comments.find((c) => c.id === parentId && c.ideaId === ideaId && !c.isDeleted);
      if (!parent) throw new Error('Comment not found.');
      topId = parent.parentId ?? parent.id;
    }
    const comment: IdeaComment = {
      id: nextId('comment'),
      ideaId,
      parentId: topId,
      authorName: 'Operator',
      authorKind: 'user',
      body: text,
      isDeleted: false,
      isMine: true,
      canEdit: true,
      canDelete: true,
      createdAt: new Date().toISOString(),
      editedAt: null,
    };
    comments.push(comment);
    return { ...comment };
  },

  async editComment(ideaId: string, commentId: string, body: string): Promise<IdeaComment> {
    const comment = comments.find((c) => c.id === commentId && c.ideaId === ideaId && !c.isDeleted);
    if (!comment) throw new Error('Comment not found.');
    comment.body = body.trim();
    comment.editedAt = new Date().toISOString();
    return { ...comment };
  },

  async deleteComment(ideaId: string, commentId: string): Promise<void> {
    const comment = comments.find((c) => c.id === commentId && c.ideaId === ideaId && !c.isDeleted);
    if (!comment) throw new Error('Comment not found.');
    comment.isDeleted = true;
    comment.body = null;
    comment.authorName = null;
    comment.canEdit = false;
    comment.canDelete = false;
    comment.isMine = false;
  },

  async reorderPriority(orderedIds: string[]): Promise<Idea[]> {
    // Slot preserving (D11): the given ids occupy their OWN current slots
    // (sorted ascending), reassigned in the given order - ids outside the
    // given set (a different page) are untouched.
    const targets = orderedIds
      .map((id) => findRecord(id))
      .filter((r): r is MockIdeaRecord => Boolean(r) && !r!.idea.mergedIntoId);
    const slots = targets.map((r) => r.idea.priority).sort((a, b) => a - b);
    targets
      .slice()
      .sort((a, b) => orderedIds.indexOf(a.idea.id) - orderedIds.indexOf(b.idea.id))
      .forEach((r, i) => {
        r.idea.priority = slots[i];
      });
    return allPresented(true, 'all').filter((i) => orderedIds.includes(i.id));
  },

  async suggestClusters(): Promise<IdeaClusterSuggestions> {
    return { clusters: [], degraded: false };
  },

  async remove(id: string): Promise<void> {
    const rec = requireRecord(id);
    // Deleting a survivor restores its children first (AC-94-10).
    if (records.some((r) => r.idea.mergedIntoId === id)) {
      await mockIdeationService.unmerge(id);
    }
    records = records.filter((r) => r.idea.id !== rec.idea.id);
    comments = comments.filter((c) => c.ideaId !== rec.idea.id);
  },

  async merge(survivorId: string, ideaIds: string[]): Promise<Idea> {
    const unique = Array.from(new Set(ideaIds));
    if (unique.length < 2) throw new Error('Select at least two ideas to merge.');
    if (!unique.includes(survivorId)) throw new Error('The survivor must be one of the selected ideas.');
    const recs = unique.map((id) => requireRecord(id));
    const productIds = new Set(recs.map((r) => r.idea.productId));
    if (productIds.size > 1) throw new Error('Selected ideas must share one product.');
    const testFlags = new Set(recs.map((r) => r.idea.isTest));
    if (testFlags.size > 1) throw new Error('Cannot mix test and real ideas.');
    if (recs.some((r) => statusByKey(r.idea.status).isArchived)) {
      throw new Error('An archived idea cannot be merged.');
    }
    if (recs.some((r) => r.idea.mergedIntoId)) {
      throw new Error('An already-merged idea cannot be merged again.');
    }

    const survivorRec = requireRecord(survivorId);
    if (!survivorRec.idea.ideaNumber) {
      survivorRec.idea.ideaNumber = `IDEA-${String(seq).padStart(4, '0')}`;
    }

    for (const rec of recs) {
      if (rec.idea.id === survivorId) continue;
      // Flatten (D2/D6): a member that is itself a survivor re-points its
      // own children to the NEW survivor.
      for (const grandchild of records.filter((r) => r.idea.mergedIntoId === rec.idea.id)) {
        grandchild.idea.mergedIntoId = survivorId;
      }
      rec.preMergeVotes = { upvotes: rec.idea.upvotes, downvotes: rec.idea.downvotes };
      survivorRec.idea.upvotes += rec.idea.upvotes;
      survivorRec.idea.downvotes += rec.idea.downvotes;
      rec.idea.mergedIntoId = survivorId;
      rec.mergedAt = new Date().toISOString();
    }
    return mockIdeationService.getIdea(survivorId);
  },

  async unmerge(id: string): Promise<Idea[]> {
    const rec = requireRecord(id);
    const children = records.filter((r) => r.idea.mergedIntoId === id);
    if (!rec.idea.mergedIntoId && children.length === 0) {
      throw new Error('This idea is not part of a merge.');
    }
    const restore = (child: MockIdeaRecord) => {
      const survivor = findRecord(child.idea.mergedIntoId!);
      if (survivor && child.preMergeVotes) {
        survivor.idea.upvotes -= child.preMergeVotes.upvotes;
        survivor.idea.downvotes -= child.preMergeVotes.downvotes;
      }
      child.idea.mergedIntoId = null;
      child.mergedAt = null;
      child.preMergeVotes = null;
    };

    if (rec.idea.mergedIntoId) {
      restore(rec);
      return [await mockIdeationService.getIdea(id)];
    }
    // Dissolving a survivor restores every child (AC-94-08).
    for (const child of children) restore(child);
    return Promise.all(children.map((c) => mockIdeationService.getIdea(c.idea.id)));
  },

  async listMerged(id: string): Promise<Idea[]> {
    requireRecord(id);
    const ranks = rankMap({ includeTest: true });
    return records
      .filter((r) => r.idea.mergedIntoId === id)
      .map((r) => present(r.idea, ranks));
  },

  async getBoard(opts?: { includeTest?: boolean; productId?: string }): Promise<Board> {
    const includeTest = Boolean(opts?.includeTest);
    const ranks = rankMap({ includeTest, productId: opts?.productId });
    const scoped = records
      .filter((r) => !r.idea.mergedIntoId)
      .filter((r) => (includeTest ? true : !r.idea.isTest))
      .filter((r) => (opts?.productId ? r.idea.productId === opts.productId : true));

    const columns: BoardColumn[] = BOARD_STATUS_KEYS.map((key) => {
      const status = statusByKey(key);
      const ideas = scoped
        .filter((r) => r.idea.status === key)
        .map((r) => present(r.idea, ranks))
        .sort((a, b) => a.priority - b.priority);
      return { statusId: status.id, key: status.key, title: status.label, color: status.color, ideas };
    });
    return { columns };
  },
};
