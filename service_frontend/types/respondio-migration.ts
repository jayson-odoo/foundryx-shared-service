/**
 * respond.io migration tool types (plan 33, roadmap A6). Mirrors the real
 * backend contract §5.2 (as built across S1-S5) exactly; the source-vendor
 * shapes (`shapes.py` field names) never leak past the backend - everything
 * below is already camelCase, Z-suffixed wire.
 *
 * `connectionId`/`workspaceId` come from the EXISTING `Connection` (filtered
 * `provider === 'respondio'`) and `Workspace` catalogs (`types/integration.ts`,
 * `types/omnichannel.ts`) - this module never redeclares those.
 */

export type MigrationMode = 'dry_run' | 'run';
export type MigrationSourceKind = 'api' | 'csv';

/** Lifecycle states shared with the generic `background_jobs` row this job
 *  type rides (`types/jobs.ts` `JobStatus`) - repeated here so this module
 *  stays self-contained for its own registries (status badge, segments). */
export type MigrationJobStatus =
  | 'pending'
  | 'running'
  | 'needs_review'
  | 'done'
  | 'failed'
  | 'aborted';

export const MIGRATION_JOB_IN_FLIGHT: ReadonlySet<MigrationJobStatus> = new Set<MigrationJobStatus>([
  'pending',
  'running',
]);

/** One respond.io space channel (`GET /space/channel`). */
export interface MigrationSourceChannel {
  id: string;
  name: string;
  /** Vendor `ChannelSource` value, e.g. `whatsapp_cloud`, `facebook`. */
  source: string;
}

/** One respond.io space user (`GET /space/user`). */
export interface MigrationSourceUser {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  role: string;
  teamId: string | null;
  teamName: string | null;
}

/** One respond.io team (derived from `SpaceUser.team`). */
export interface MigrationSourceTeam {
  id: string;
  name: string;
}

/** One respond.io custom field (`GET /space/custom_field`). */
export interface MigrationSourceField {
  id: string;
  name: string;
  dataType: 'text' | 'list' | 'checkbox' | 'email' | 'number' | 'url' | 'date' | 'time';
}

/** A Foundryx channel offered as a mapping target - only channels whose
 *  `channelType` is compatible with a given source appear as options
 *  (AC-MIG-04, foolproof-UI). */
export interface MigrationTargetChannel {
  id: string;
  name: string;
  channelType: string;
}

/** A Foundryx lifecycle stage offered as a mapping target - never created
 *  by the mapping UI (AC-MIG-06). */
export interface MigrationTargetStage {
  statusId: string;
  label: string;
}

/** `GET /omnichannel/migration/preflight` (AC-MIG-14). Read-only.
 *
 *  `lifecycles` is a decision taken where the plan's §5.2 preflight
 *  response shape was silent (see S0 report): AC-MIG-06 needs "each
 *  observed source lifecycle label" to build the Lifecycle section BEFORE
 *  any dry run exists, but the plan's preflight calls
 *  (`/space/channel`, `/space/user`, `/space/custom_field`) never touch a
 *  contact, so nothing else in the contract can supply these labels. S1's
 *  preflight must additionally do one read-only distinct-value pass over
 *  `contact.lifecycle` (still zero writes, per AC-MIG-14). */
export interface MigrationPreflight {
  apiAvailable: boolean;
  spaceLabel: string;
  channels: MigrationSourceChannel[];
  users: MigrationSourceUser[];
  teams: MigrationSourceTeam[];
  fields: MigrationSourceField[];
  lifecycles: string[];
  targetChannels: MigrationTargetChannel[];
  targetStages: MigrationTargetStage[];
  warnings: string[];
}

export interface MigrationChannelMapEntry {
  sourceChannelId: string;
  /** `null` = "Skip this channel" (AC-MIG-04). */
  targetChannelId: string | null;
}

export interface MigrationUserMapEntry {
  sourceUserId: string;
  targetUserId: string | null;
}

export interface MigrationTeamMapEntry {
  sourceTeamId: string;
  targetTeamId: string | null;
}

export interface MigrationLifecycleMapEntry {
  sourceLabel: string;
  /** `null` = unmapped - allowed, reported as a blocker (AC-MIG-06). */
  targetStatusId: string | null;
}

/** `POST /omnichannel/migration/jobs` body (§5.2, extended by S5 D-A6-25).
 *  `connectionId` is required for `source: 'api'` only - a CSV-mode
 *  migration from a customer with zero API access never created a
 *  connection row at all (AC-MIG-46, the setup form's own source toggle). */
export interface CreateMigrationJobInput {
  connectionId: string | null;
  workspaceId: string;
  mode: MigrationMode;
  source: MigrationSourceKind;
  channelMap: MigrationChannelMapEntry[];
  userMap: MigrationUserMapEntry[];
  teamMap: MigrationTeamMapEntry[];
  lifecycleMap: MigrationLifecycleMapEntry[];
  messagesSince?: string | null;
  contactsOnly?: boolean;
  /** S5 (AC-MIG-47) - the storage key `POST /omnichannel/migration/uploads`
   *  (`kind=contacts`) returned, required when `source === 'csv'`. */
  contactsCsvKey?: string | null;
  /** systemKey -> the file's own header string (`MIGRATION_CSV_HEADER_KEYS`
   *  below); an unmapped key falls back to the backend's own case-
   *  insensitive alias guess (`_HEADER_ALIASES`, migration_service.py). */
  csvHeaderMap?: Record<string, string>;
  /** S5 (D-A6-19/25) - the storage key `POST .../uploads` (`kind=snippets`)
   *  returned; optional in BOTH modes (respond.io has no snippets endpoint,
   *  so this is CSV-or-manual only either way). */
  snippetsCsvKey?: string | null;
}

/** The CSV-mode contacts header map (plan §5.6, `CSV_HEADER_KEYS` in
 *  `migration_service.py`) - a fixed, small set of system field keys the
 *  backend understands; NOT the file's headers (those come back from
 *  `POST .../uploads` and populate each row's option list). Custom fields
 *  and tags are deliberately not part of this map (D-A6-25) - only the
 *  separate contacts-import wizard (AC-MIG-46) finds-or-creates those. */
export const MIGRATION_CSV_HEADER_KEYS: { key: string; label: string }[] = [
  { key: 'externalId', label: 'Contact ID' },
  { key: 'firstName', label: 'First name' },
  { key: 'lastName', label: 'Last name' },
  { key: 'phone', label: 'Phone' },
  { key: 'email', label: 'Email' },
  { key: 'language', label: 'Language' },
  { key: 'countryCode', label: 'Country' },
  { key: 'lifecycle', label: 'Lifecycle' },
];

/** `POST /omnichannel/migration/uploads` response (S5, AC-MIG-46/47) - the
 *  storage key the job payload then carries, plus the sniffed file's row
 *  count and headers so the setup form can render the header-map step
 *  without a second round trip. */
export interface MigrationUploadResult {
  key: string;
  rowCount: number;
  headers: string[];
}

export type MigrationEntityKey =
  | 'contacts'
  | 'fields'
  | 'tags'
  | 'identities'
  | 'messages'
  | 'media'
  | 'events'
  | 'quickReplies';

export const MIGRATION_ENTITY_ORDER: MigrationEntityKey[] = [
  'contacts',
  'fields',
  'tags',
  'identities',
  'messages',
  'media',
  'events',
  'quickReplies',
];

export interface MigrationEntityCounts {
  fetched: number;
  wouldCreate: number;
  wouldUpdate: number;
  wouldSkip: number;
  errors: number;
}

export interface MigrationReport {
  entities: Record<MigrationEntityKey, MigrationEntityCounts>;
  messagesWithInferredTimestamp: number;
  /** S4 (D-A6-22) - messages older than the job's `messagesSince` floor,
   *  excluded from the walk entirely (never written, never an error). */
  messagesSkippedBeforeFloor: number;
  blockers: string[];
  samples: {
    contacts: Record<string, unknown>[];
    messages: Record<string, unknown>[];
  };
}

/** One row of `GET /omnichannel/migration/jobs/{jobId}/failures.csv`, and of
 *  the in-page failure `DataGrid` (AC-MIG-08). */
export interface MigrationFailureRow {
  entity: string;
  sourceId: string;
  sourceLabel: string;
  reason: string;
  action: string;
}

/** `MigrationJobItem` (§5.2) - the list + detail read shape. Two decisions
 *  taken where the plan was silent (see S0 report):
 *  - `entityCounts`: the list's Contacts/Messages columns (AC-MIG-02) need
 *    to read WHILE a job is still running, before `report` exists, so the
 *    live per-entity counts ride their own field off the job's
 *    `cursor_json`, separate from the dry-run/final `report`.
 *  - `failureSample`: the detail page's in-page failure `DataGrid`
 *    (AC-MIG-08) needs bounded rows inline with the job read, distinct from
 *    the full, authed CSV export (D-A6-23) - riding the SAME GET avoids a
 *    second round trip (and avoids parsing the CSV client-side, which is
 *    fragile the moment a reason string itself contains a comma). Capped
 *    (first 50); `failureCount` is the true total and drives the CSV
 *    download button's visibility. */
export interface MigrationJob {
  id: string;
  mode: MigrationMode;
  source: MigrationSourceKind;
  connectionId: string;
  spaceLabel: string;
  workspaceId: string;
  workspaceName: string;
  status: MigrationJobStatus;
  progressTotal: number;
  progressDone: number;
  progressFailed: number;
  entityCounts: { contacts: number; messages: number } | null;
  report: MigrationReport | null;
  failureCount: number;
  failureSample: MigrationFailureRow[];
  startedAt: string | null; // ISO Z
  finishedAt: string | null; // ISO Z
  createdAt: string; // ISO Z
  actorUserName: string | null;
  /** S6 (AC-MIG-08) - the milestone log, populated on the detail read
   *  (`GET .../jobs/{id}`) only; the list read always sends `[]`. */
  logs: MigrationJobLogEntry[];
}

/** Milestone log line rendered on the detail page (mirrors `types/jobs.ts`
 *  `JobLogEntry` - this job type rides the same `background_jobs` row). */
export interface MigrationJobLogEntry {
  ts: string; // ISO Z
  level: string; // info | warning | error
  message: string;
}

/** The subset of `CreateMigrationJobInput` that defines "the exact mapping"
 *  (D-A6-14 / AC-MIG-07/20): `mode` is deliberately excluded so a `dry_run`
 *  and its matching `run` share one hash. `contactsCsvKey`/`csvHeaderMap`
 *  mirror the backend's own `_mapping_hash` (S5, D-A6-25) - a re-uploaded
 *  CSV or a changed header map IS a different mapping; `snippetsCsvKey`
 *  stays excluded on both sides (quick replies are independent of "the
 *  mapping"). */
export type MigrationMappingShape = Pick<
  CreateMigrationJobInput,
  | 'connectionId'
  | 'workspaceId'
  | 'channelMap'
  | 'userMap'
  | 'teamMap'
  | 'lifecycleMap'
  | 'contactsOnly'
  | 'messagesSince'
  | 'contactsCsvKey'
  | 'csvHeaderMap'
>;

function sortedBy<T, K extends string>(rows: T[], key: (row: T) => K): T[] {
  return [...rows].sort((a, b) => key(a).localeCompare(key(b)));
}

/**
 * Deterministic mapping hash (AC-MIG-58 "mapping hash stability") - same
 * mapping content (any array order) always yields the same hash; the "Start
 * migration" gate (client, `use-migration-form.tsx`) and the backend's
 * `dry_run_required` check (mock: `respondio-migration-service.mock.ts`;
 * real: the S2 job service) must derive the SAME value from the SAME input
 * or the gate lies. A canonical (key-sorted) JSON string, then djb2 folded
 * to a short hex digest - a real crypto hash is unwarranted for an
 * equality check that never leaves the browser/mock boundary.
 */
export function computeMappingHash(shape: MigrationMappingShape): string {
  const canonical = {
    connectionId: shape.connectionId,
    workspaceId: shape.workspaceId,
    channelMap: sortedBy(shape.channelMap, (r) => r.sourceChannelId).map((r) => [r.sourceChannelId, r.targetChannelId]),
    userMap: sortedBy(shape.userMap, (r) => r.sourceUserId).map((r) => [r.sourceUserId, r.targetUserId]),
    teamMap: sortedBy(shape.teamMap, (r) => r.sourceTeamId).map((r) => [r.sourceTeamId, r.targetTeamId]),
    lifecycleMap: sortedBy(shape.lifecycleMap, (r) => r.sourceLabel).map((r) => [r.sourceLabel, r.targetStatusId]),
    contactsOnly: !!shape.contactsOnly,
    messagesSince: shape.messagesSince ?? null,
    contactsCsvKey: shape.contactsCsvKey ?? null,
    csvHeaderMap: sortedBy(Object.entries(shape.csvHeaderMap ?? {}), (r) => r[0]),
  };
  const json = JSON.stringify(canonical);
  let hash = 5381;
  for (let i = 0; i < json.length; i++) {
    hash = ((hash << 5) + hash + json.charCodeAt(i)) | 0;
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}
