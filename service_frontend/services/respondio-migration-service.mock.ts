/**
 * Mock respond.io migration service (S0 MOCK - swap to real in S6, plan 33).
 * In-memory job store spanning every `MigrationJobStatus` (AC-MIG-09):
 * `done` dry run, `done` real run (with failures), `running` (advances on
 * each read, mirrors `broadcast-service.mock.ts`'s SENDING tick), `failed`,
 * `aborted`, `needs_review`. `preflight` returns a fixed source-space
 * snapshot with one channel that has NO compatible target (exercises the
 * forced "Skip this channel" rule, AC-MIG-04) and one source user whose
 * email matches the demo tenant Admin (exercises the People prefill rule,
 * AC-MIG-05).
 *
 * `dry_run_required` / `migration_in_progress` (AC-MIG-20/21) are enforced
 * here against an in-memory ledger keyed by `connectionId:workspaceId`, the
 * SAME `computeMappingHash` the setup form uses client-side to disable
 * "Start migration" (`migration-schema.ts`) - one hash function, not two.
 */
import { ApiError } from '@/lib/api-client';
import type {
  CreateMigrationJobInput,
  MigrationEntityCounts,
  MigrationFailureRow,
  MigrationJob,
  MigrationPreflight,
  MigrationReport,
} from '@/types/respondio-migration';
import type { ListQuery, ListResult } from '@/types/resource';
import { computeMappingHash } from '@/types/respondio-migration';
import { delay, runQuery, type QueryAdapter } from './mock-query';
import type { RespondioMigrationService } from './respondio-migration-service';

function conflictError(reason: string, message: string): ApiError {
  return new ApiError(message, 409, null, { reason });
}

const NOW = Date.now();
const iso = (msAgo: number) => new Date(NOW - msAgo).toISOString();
const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

function zeroCounts(): MigrationEntityCounts {
  return { fetched: 0, wouldCreate: 0, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
}

function emptyReport(): MigrationReport {
  return {
    entities: {
      contacts: zeroCounts(),
      fields: zeroCounts(),
      tags: zeroCounts(),
      identities: zeroCounts(),
      messages: zeroCounts(),
      media: zeroCounts(),
      events: zeroCounts(),
      quickReplies: zeroCounts(),
    },
    messagesWithInferredTimestamp: 0,
    blockers: [],
    samples: { contacts: [], messages: [] },
  };
}

const MOCK_FAILURE_ROWS: MigrationFailureRow[] = [
  { entity: 'media', sourceId: 'rio-msg-4821', sourceLabel: 'image attachment', reason: '404 fetching source URL', action: 'skipped' },
  { entity: 'identity', sourceId: 'rio-cnt-118', sourceLabel: 'Alicia Chan', reason: 'no derivable external id', action: 'skipped' },
];

const MOCK_CONNECTION_ID = 'conn-rio-mock-1';
const MOCK_WORKSPACE_ID = 'wsp-001';
const MOCK_WORKSPACE_NAME = 'Main workspace';

/** One source space, fixed for S0 - S1 wires this to the real client walk. */
function mockPreflight(): MigrationPreflight {
  return {
    apiAvailable: true,
    spaceLabel: 'Acme Support (respond.io)',
    channels: [
      { id: 'rio-chn-1', name: 'WhatsApp - Support line', source: 'whatsapp_cloud' },
      { id: 'rio-chn-2', name: 'Instagram - @acmesupport', source: 'instagram' },
      { id: 'rio-chn-3', name: 'Telegram bot', source: 'telegram' },
    ],
    users: [
      { id: 'rio-usr-1', firstName: 'Demo', lastName: 'Admin', email: 'demo@example.com', role: 'owner', teamId: 'rio-team-1', teamName: 'Support' },
      { id: 'rio-usr-2', firstName: 'Priya', lastName: 'Nair', email: 'priya.nair@respond.example', role: 'agent', teamId: 'rio-team-1', teamName: 'Support' },
      { id: 'rio-usr-3', firstName: 'Sam', lastName: 'Ito', email: 'sam.ito@respond.example', role: 'manager', teamId: null, teamName: null },
    ],
    teams: [
      { id: 'rio-team-1', name: 'Support' },
      { id: 'rio-team-2', name: 'Sales' },
    ],
    fields: [
      { id: 'rio-fld-1', name: 'Plan tier', dataType: 'list' },
      { id: 'rio-fld-2', name: 'Renewal date', dataType: 'date' },
    ],
    lifecycles: ['lead', 'customer', 'churned'],
    // Only WhatsApp is connected in the target workspace for this mock - the
    // Instagram and Telegram source channels have no compatible target
    // (AC-MIG-04: forced "Skip this channel").
    targetChannels: [{ id: 'chn-demo', name: 'Demo WhatsApp (sandbox)', channelType: 'WHATSAPP' }],
    targetStages: [
      { statusId: 'stg-lead', label: 'Lead' },
      { statusId: 'stg-customer', label: 'Customer' },
      { statusId: 'stg-churned', label: 'Churned' },
    ],
    warnings: [],
  };
}

interface JobRow extends MigrationJob {
  _lastTick?: number;
}

let jobSeq = 1;
const nextJobId = () => `mig-job-${String(jobSeq++).padStart(3, '0')}`;

/** `(connectionId:workspaceId)` -> last successful dry run's mapping hash +
 *  timestamp (AC-MIG-20's 24h gate). */
const dryRunLedger = new Map<string, { hash: string; at: number }>();

function ledgerKey(connectionId: string, workspaceId: string): string {
  return `${connectionId}:${workspaceId}`;
}

function seed(): JobRow[] {
  jobSeq = 1;
  const rows: JobRow[] = [];

  // 1. Successful DRY RUN (unlocks "Start migration" for its exact mapping).
  {
    const id = nextJobId();
    const report = emptyReport();
    report.entities.contacts = { fetched: 214, wouldCreate: 190, wouldUpdate: 24, wouldSkip: 0, errors: 0 };
    report.entities.tags = { fetched: 9, wouldCreate: 9, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    report.entities.fields = { fetched: 2, wouldCreate: 2, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    report.entities.identities = { fetched: 214, wouldCreate: 198, wouldUpdate: 0, wouldSkip: 16, errors: 0 };
    report.entities.messages = { fetched: 5820, wouldCreate: 5820, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    report.entities.media = { fetched: 640, wouldCreate: 0, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    report.entities.events = { fetched: 428, wouldCreate: 428, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    report.messagesWithInferredTimestamp = 312;
    report.blockers = [
      '16 contacts have no lifecycle mapping and will land with no lifecycle stage.',
      'Instagram - @acmesupport and Telegram bot have no compatible target channel and will be skipped.',
    ];
    report.samples.contacts = [{ name: 'Alicia Chan', phone: '+15551234501' }];
    report.samples.messages = [{ body: 'Hi, is my order ready?', direction: 'incoming' }];
    const hash = computeMappingHash({
      connectionId: MOCK_CONNECTION_ID,
      workspaceId: MOCK_WORKSPACE_ID,
      channelMap: [
        { sourceChannelId: 'rio-chn-1', targetChannelId: 'chn-demo' },
        { sourceChannelId: 'rio-chn-2', targetChannelId: null },
        { sourceChannelId: 'rio-chn-3', targetChannelId: null },
      ],
      userMap: [
        { sourceUserId: 'rio-usr-1', targetUserId: 'usr-001' },
        { sourceUserId: 'rio-usr-2', targetUserId: null },
        { sourceUserId: 'rio-usr-3', targetUserId: null },
      ],
      teamMap: [
        { sourceTeamId: 'rio-team-1', targetTeamId: null },
        { sourceTeamId: 'rio-team-2', targetTeamId: null },
      ],
      lifecycleMap: [{ sourceLabel: 'lead', targetStatusId: 'stg-lead' }],
      contactsOnly: false,
      messagesSince: null,
    });
    dryRunLedger.set(ledgerKey(MOCK_CONNECTION_ID, MOCK_WORKSPACE_ID), { hash, at: NOW - 30 * MIN });
    rows.push({
      id,
      mode: 'dry_run',
      source: 'api',
      connectionId: MOCK_CONNECTION_ID,
      spaceLabel: 'Acme Support (respond.io)',
      workspaceId: MOCK_WORKSPACE_ID,
      workspaceName: MOCK_WORKSPACE_NAME,
      status: 'done',
      progressTotal: 214,
      progressDone: 214,
      progressFailed: 0,
      entityCounts: { contacts: 214, messages: 5820 },
      report,
      failureCount: 0,
      failureSample: [],
      startedAt: iso(35 * MIN),
      finishedAt: iso(30 * MIN),
      createdAt: iso(36 * MIN),
      actorUserName: 'Demo Admin',
    });
  }

  // 2. Completed REAL RUN, with failures.
  {
    const id = nextJobId();
    const report = emptyReport();
    report.entities.contacts = { fetched: 214, wouldCreate: 190, wouldUpdate: 24, wouldSkip: 0, errors: 0 };
    report.entities.identities = { fetched: 214, wouldCreate: 198, wouldUpdate: 0, wouldSkip: 16, errors: 0 };
    report.entities.messages = { fetched: 5820, wouldCreate: 5798, wouldUpdate: 0, wouldSkip: 0, errors: 22 };
    report.entities.media = { fetched: 640, wouldCreate: 611, wouldUpdate: 0, wouldSkip: 0, errors: 29 };
    report.entities.events = { fetched: 428, wouldCreate: 428, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    report.messagesWithInferredTimestamp = 305;
    report.blockers = [];
    rows.push({
      id,
      mode: 'run',
      source: 'api',
      connectionId: MOCK_CONNECTION_ID,
      spaceLabel: 'Acme Support (respond.io)',
      workspaceId: MOCK_WORKSPACE_ID,
      workspaceName: MOCK_WORKSPACE_NAME,
      status: 'done',
      progressTotal: 214,
      progressDone: 214,
      progressFailed: 22,
      entityCounts: { contacts: 214, messages: 5798 },
      report,
      failureCount: 22,
      failureSample: MOCK_FAILURE_ROWS,
      startedAt: iso(2 * DAY),
      finishedAt: iso(2 * DAY - 40 * MIN),
      createdAt: iso(2 * DAY + 5 * MIN),
      actorUserName: 'Demo Admin',
    });
  }

  // 3. RUNNING - advances on each read (mirrors broadcast SENDING tick).
  {
    const id = nextJobId();
    rows.push({
      id,
      mode: 'run',
      source: 'api',
      connectionId: MOCK_CONNECTION_ID,
      spaceLabel: 'Acme Support (respond.io)',
      workspaceId: MOCK_WORKSPACE_ID,
      workspaceName: MOCK_WORKSPACE_NAME,
      status: 'running',
      progressTotal: 340,
      progressDone: 96,
      progressFailed: 1,
      entityCounts: { contacts: 96, messages: 1840 },
      report: null,
      failureCount: 1,
      failureSample: [MOCK_FAILURE_ROWS[0]],
      startedAt: iso(6 * MIN),
      finishedAt: null,
      createdAt: iso(7 * MIN),
      actorUserName: 'Demo Admin',
      _lastTick: NOW,
    });
  }

  // 4. NEEDS_REVIEW - media volume exceeded the storage warning threshold.
  {
    const id = nextJobId();
    const report = emptyReport();
    report.entities.contacts = { fetched: 90, wouldCreate: 90, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    report.entities.media = { fetched: 3200, wouldCreate: 1800, wouldUpdate: 0, wouldSkip: 0, errors: 1400 };
    report.blockers = ['Storage quota was exceeded partway through the media phase.'];
    rows.push({
      id,
      mode: 'run',
      source: 'api',
      connectionId: MOCK_CONNECTION_ID,
      spaceLabel: 'Acme Support (respond.io)',
      workspaceId: MOCK_WORKSPACE_ID,
      workspaceName: MOCK_WORKSPACE_NAME,
      status: 'needs_review',
      progressTotal: 90,
      progressDone: 90,
      progressFailed: 1400,
      entityCounts: { contacts: 90, messages: 3400 },
      report,
      failureCount: 1400,
      failureSample: MOCK_FAILURE_ROWS,
      startedAt: iso(5 * DAY),
      finishedAt: iso(5 * DAY - 90 * MIN),
      createdAt: iso(5 * DAY + 5 * MIN),
      actorUserName: 'Demo Admin',
    });
  }

  // 5. FAILED.
  {
    const id = nextJobId();
    rows.push({
      id,
      mode: 'run',
      source: 'api',
      connectionId: MOCK_CONNECTION_ID,
      spaceLabel: 'Acme Support (respond.io)',
      workspaceId: MOCK_WORKSPACE_ID,
      workspaceName: MOCK_WORKSPACE_NAME,
      status: 'failed',
      progressTotal: 214,
      progressDone: 12,
      progressFailed: 0,
      entityCounts: { contacts: 12, messages: 0 },
      report: null,
      failureCount: 0,
      failureSample: [],
      startedAt: iso(7 * DAY),
      finishedAt: iso(7 * DAY - 60_000),
      createdAt: iso(7 * DAY + 5 * MIN),
      actorUserName: 'Demo Admin',
    });
  }

  // 6. ABORTED - partial counts, cursor intact (AC-MIG-28).
  {
    const id = nextJobId();
    rows.push({
      id,
      mode: 'run',
      source: 'api',
      connectionId: MOCK_CONNECTION_ID,
      spaceLabel: 'Acme Support (respond.io)',
      workspaceId: MOCK_WORKSPACE_ID,
      workspaceName: MOCK_WORKSPACE_NAME,
      status: 'aborted',
      progressTotal: 214,
      progressDone: 58,
      progressFailed: 0,
      entityCounts: { contacts: 58, messages: 902 },
      report: null,
      failureCount: 0,
      failureSample: [],
      startedAt: iso(8 * DAY),
      finishedAt: iso(8 * DAY - 20 * MIN),
      createdAt: iso(8 * DAY + 5 * MIN),
      actorUserName: 'Demo Admin',
    });
  }

  return rows;
}

let rows: JobRow[] = seed();

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetRespondioMigrations(): void {
  rows = seed();
}

function tick(row: JobRow): void {
  if (row.status !== 'running') return;
  const last = row._lastTick ?? NOW;
  const elapsedSec = (Date.now() - last) / 1000;
  const steps = Math.floor(elapsedSec / 3);
  if (steps <= 0) return;
  row._lastTick = Date.now();
  for (let i = 0; i < steps && row.progressDone < row.progressTotal; i++) {
    row.progressDone += 6;
    if (row.entityCounts) {
      row.entityCounts = {
        contacts: Math.min(214, row.entityCounts.contacts + 6),
        messages: row.entityCounts.messages + 60,
      };
    }
  }
  if (row.progressDone >= row.progressTotal) {
    row.progressDone = row.progressTotal;
    row.status = 'done';
    row.finishedAt = new Date().toISOString();
    row.report = emptyReport();
    row.report.entities.contacts = { fetched: 214, wouldCreate: 214, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
    row.report.entities.messages = {
      fetched: row.entityCounts?.messages ?? 0,
      wouldCreate: row.entityCounts?.messages ?? 0,
      wouldUpdate: 0,
      wouldSkip: 0,
      errors: row.progressFailed,
    };
  }
}

function tickAll(): void {
  for (const r of rows) tick(r);
}

function toJob(row: JobRow): MigrationJob {
  const { _lastTick, ...rest } = row;
  void _lastTick;
  return rest;
}

const adapter: QueryAdapter<JobRow> = {
  searchFields: ['spaceLabel', 'workspaceName'],
  getField: (row, field) => {
    switch (field) {
      case 'status':
        return row.status;
      case 'mode':
        return row.mode;
      case 'spaceLabel':
        return row.spaceLabel;
      case 'workspaceName':
        return row.workspaceName;
      case 'createdAt':
        return row.createdAt;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}

export const mockRespondioMigrationService: RespondioMigrationService = {
  async preflight(connectionId, workspaceId) {
    if (!connectionId || !workspaceId) {
      throw fieldErrorsError('Choose a connection and a target workspace.', {
        connectionId: connectionId ? '' : 'Choose a connection.',
        workspaceId: workspaceId ? '' : 'Choose a target workspace.',
      });
    }
    return delay(mockPreflight(), 400);
  },

  async listJobs(query: ListQuery): Promise<ListResult<MigrationJob>> {
    tickAll();
    let filteredBySegment = rows;
    if (query.segment && query.segment !== 'all') {
      filteredBySegment = rows.filter((r) => r.status === query.segment);
    }
    const result = runQuery(filteredBySegment, { ...query, segment: undefined }, adapter);
    return delay({ ...result, data: result.data.map(toJob) }, 250);
  },

  async getJob(jobId: string): Promise<MigrationJob> {
    tickAll();
    const row = rows.find((r) => r.id === jobId);
    if (!row) throw new ApiError('Migration job not found.', 404, null, null);
    return delay(toJob(row), 200);
  },

  async createJob(input: CreateMigrationJobInput): Promise<MigrationJob> {
    if (!input.connectionId || !input.workspaceId) {
      throw fieldErrorsError('Choose a connection and a target workspace.', {
        connectionId: input.connectionId ? '' : 'Choose a connection.',
        workspaceId: input.workspaceId ? '' : 'Choose a target workspace.',
      });
    }
    const key = ledgerKey(input.connectionId, input.workspaceId);
    const inFlight = rows.find(
      (r) =>
        r.connectionId === input.connectionId &&
        r.workspaceId === input.workspaceId &&
        (r.status === 'pending' || r.status === 'running'),
    );
    if (inFlight) throw conflictError('migration_in_progress', 'A migration is already running for this workspace.');

    if (input.mode === 'run') {
      const hash = computeMappingHash(input);
      const entry = dryRunLedger.get(key);
      const fresh = entry && entry.hash === hash && Date.now() - entry.at < 24 * HOUR;
      if (!fresh) {
        throw conflictError('dry_run_required', 'Run a dry run for this exact mapping first.');
      }
    }

    const id = nextJobId();
    const row: JobRow = {
      id,
      mode: input.mode,
      source: input.source,
      connectionId: input.connectionId,
      spaceLabel: mockPreflight().spaceLabel,
      workspaceId: input.workspaceId,
      workspaceName: MOCK_WORKSPACE_NAME,
      status: input.mode === 'dry_run' ? 'running' : 'pending',
      progressTotal: 214,
      progressDone: 0,
      progressFailed: 0,
      entityCounts: { contacts: 0, messages: 0 },
      report: null,
      failureCount: 0,
      failureSample: [],
      startedAt: new Date().toISOString(),
      finishedAt: null,
      createdAt: new Date().toISOString(),
      actorUserName: 'You',
      _lastTick: Date.now(),
    };
    rows = [row, ...rows];

    if (input.mode === 'dry_run') {
      // Dry runs settle fast in the mock (a real dry run still walks the
      // whole space, but nothing is written) - land it `done` immediately
      // and register the mapping hash so "Start migration" unlocks.
      row.status = 'running';
      setTimeout(() => {
        row.status = 'done';
        row.progressDone = row.progressTotal;
        row.finishedAt = new Date().toISOString();
        row.report = emptyReport();
        row.report.entities.contacts = { fetched: 214, wouldCreate: 190, wouldUpdate: 24, wouldSkip: 0, errors: 0 };
        row.report.entities.messages = { fetched: 5820, wouldCreate: 5820, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
        dryRunLedger.set(key, { hash: computeMappingHash(input), at: Date.now() });
      }, 1500);
    } else {
      row.status = 'running';
    }

    return delay(toJob(row), 300);
  },

  async downloadFailuresCsv(jobId: string): Promise<string> {
    const row = rows.find((r) => r.id === jobId);
    if (!row) throw new ApiError('Migration job not found.', 404, null, null);
    // The mock's sample IS the full set (S0 has no >50-row failure job); the
    // real backend re-derives the CSV from every `background_jobs.result_json`
    // failure row, not just the capped `failureSample`.
    const failureRows: MigrationFailureRow[] = row.failureSample;
    const header = 'entity,sourceId,sourceLabel,reason,action';
    const csv = [header, ...failureRows.map((f) => `${f.entity},${f.sourceId},"${f.sourceLabel}","${f.reason}",${f.action}`)].join('\n');
    return delay(csv, 200);
  },
};
