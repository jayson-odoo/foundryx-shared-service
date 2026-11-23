/** Test data for the migration page tests (parity and the new look). */
import type { MigrationEntityCounts, MigrationJob, MigrationReport } from '@/types/respondio-migration';

const counts = (fetched: number, errors = 0): MigrationEntityCounts => ({
  fetched,
  wouldCreate: fetched - errors,
  wouldUpdate: 0,
  wouldSkip: 0,
  errors,
});

const REPORT: MigrationReport = {
  entities: {
    contacts: counts(1240, 3),
    fields: counts(6),
    tags: counts(12),
    identities: counts(1240),
    messages: counts(18200),
    media: counts(340),
    events: counts(0),
    quickReplies: counts(8),
  },
  messagesWithInferredTimestamp: 0,
  messagesSkippedBeforeFloor: 0,
  blockers: [],
  samples: { contacts: [], messages: [] },
};

const job = (over: Partial<MigrationJob>): MigrationJob => ({
  id: 'job-1',
  mode: 'run',
  source: 'api',
  connectionId: 'conn-1',
  spaceLabel: 'Sales space',
  workspaceId: 'wsp-1',
  workspaceName: 'General',
  status: 'running',
  progressTotal: 0,
  progressDone: 820,
  progressFailed: 0,
  entityCounts: { contacts: 820, messages: 0 },
  report: null,
  failureCount: 0,
  failureSample: [],
  startedAt: '2026-11-18T02:00:00Z',
  finishedAt: null,
  createdAt: '2026-11-18T02:00:00Z',
  actorUserName: 'Nurul Huda',
  logs: [{ ts: '2026-11-18T02:00:05Z', level: 'info', message: 'Contacts phase started' }],
  ...over,
});

export const MIGRATION_JOBS: MigrationJob[] = [
  job({}),
  job({
    id: 'job-2',
    spaceLabel: 'Support space',
    progressTotal: 1240,
    progressDone: 820,
    progressFailed: 2,
    logs: [],
  }),
  job({
    id: 'job-3',
    mode: 'dry_run',
    source: 'csv',
    connectionId: null,
    spaceLabel: 'contacts.csv',
    status: 'done',
    progressTotal: 1240,
    progressDone: 1240,
    progressFailed: 3,
    entityCounts: { contacts: 1237, messages: 0 },
    report: REPORT,
    failureCount: 3,
    failureSample: [
      { entity: 'contact', sourceId: 'c-9', sourceLabel: 'Tan Mei Ling', reason: 'Phone number is not valid', action: 'skipped' },
    ],
    finishedAt: '2026-11-18T02:20:00Z',
    logs: [
      { ts: '2026-11-18T02:00:05Z', level: 'info', message: 'Contacts phase started' },
      { ts: '2026-11-18T02:10:00Z', level: 'warning', message: '3 contacts skipped' },
    ],
  }),
];
