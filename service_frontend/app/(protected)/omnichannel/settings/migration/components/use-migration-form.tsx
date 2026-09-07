'use client';

/**
 * The setup form's data + submit orchestration (plan 33, AC-MIG-03/07,
 * extended in S6 for CSV mode - AC-MIG-46/47). Connections and the target
 * workspace ride the EXISTING generic catalogs (`integration-service`,
 * `workspace-service`); people options ride the existing `user-service`/
 * `team-service`; only the respond.io-specific preflight + upload + job
 * creation go through `respondio-migration-service` (the real routes as of
 * S6, AC-MIG-56).
 *
 * "Start migration" is gated by a dry run for the EXACT current mapping
 * (AC-MIG-07/20). The gate is tracked in this hook's own state, set the
 * moment a `dry_run` job this session settles `done`, and compared against
 * the CURRENT form values' `computeMappingHash` on every render - so editing
 * any map row (or re-uploading a CSV) after a successful dry run immediately
 * re-locks Start. The 24h / mapping-hash rule is ALSO enforced server-side
 * (`dry_run_required`, AC-MIG-20) - this client gate is UX only.
 *
 * CSV mode (`source: 'csv'`, S6) skips preflight entirely - respond.io
 * exposes no space data to a customer with zero API access, so
 * channelMap/userMap/teamMap/lifecycleMap stay empty and the Channels/
 * People/Lifecycle sections stay hidden (they already guard on
 * `!preflight`). "Ready" for API mode needs a connection AND a settled
 * preflight; for CSV mode it needs only an uploaded contacts file.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, useWatch, type FieldPath, type UseFormReturn } from 'react-hook-form';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { integrationService } from '@/services/integration-service';
import { workspaceService } from '@/services/workspace-service';
import { userService } from '@/services/user-service';
import { teamService } from '@/services/team-service';
import { respondioMigrationService } from '@/services/respondio-migration-service';
import type { Connection } from '@/types/integration';
import type { Workspace } from '@/types/omnichannel';
import type { User } from '@/types/user';
import type { Team } from '@/types/team';
import type { MigrationJob, MigrationPreflight, MigrationUploadResult } from '@/types/respondio-migration';
import { MIGRATION_JOB_IN_FLIGHT } from '@/types/respondio-migration';
import {
  computeMappingHash,
  EMPTY_MIGRATION_FORM_VALUES,
  migrationFormSchema,
  toCreateMigrationJobInput,
  type MigrationFormValues,
} from './migration-schema';
import { SOURCE_TO_CHANNEL_TYPE } from './channel-source-map';
import { migrationJobPath } from './paths';

const POLL_MS = 2000;

/** Top-level fields the setup form has a visible slot for - a 422 path
 *  outside this set (e.g. a per-row `channelMap.0`/`lifecycleMap.0` leaf,
 *  which has no dedicated error slot on its row component) falls back to a
 *  toast instead of a silently-swallowed `setError`. */
const FORM_FIELD_PATHS: ReadonlySet<string> = new Set([
  'connectionId',
  'workspaceId',
  'messagesSince',
  'contactsCsvKey',
]);

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = (error.detail as { reason?: string } | null)?.reason;
    if (reason === 'dry_run_required') return 'Run a dry run for this exact mapping first.';
    if (reason === 'migration_in_progress') return 'A migration is already running for this workspace.';
    return error.message;
  }
  return 'Something went wrong. Please try again.';
}

/** 422 `{fieldErrors}` -> RHF field errors for the fields this form renders
 *  an error slot for; every other path is summarized as a toast (still
 *  surfaced, never silently dropped). */
function applyFieldErrors(form: UseFormReturn<MigrationFormValues>, error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 422) return false;
  const fieldErrors = (error.detail as { fieldErrors?: Record<string, string> } | null)?.fieldErrors;
  if (!fieldErrors) return false;
  const overflow: string[] = [];
  for (const [path, message] of Object.entries(fieldErrors)) {
    if (!message) continue;
    if (FORM_FIELD_PATHS.has(path)) {
      form.setError(path as FieldPath<MigrationFormValues>, { type: 'server', message });
    } else {
      overflow.push(message);
    }
  }
  if (overflow.length > 0) toast.error(overflow.join(' '));
  return true;
}

function compatibleTargetIds(sourceValue: string, preflight: MigrationPreflight): string[] {
  const channelType = SOURCE_TO_CHANNEL_TYPE[sourceValue] ?? null;
  if (!channelType) return [];
  return preflight.targetChannels.filter((t) => t.channelType === channelType).map((t) => t.id);
}

function seedFromPreflight(pf: MigrationPreflight, tenantUsers: User[]): Partial<MigrationFormValues> {
  return {
    channelMap: pf.channels.map((c) => {
      const compatible = compatibleTargetIds(c.source, pf);
      return { sourceChannelId: c.id, targetChannelId: compatible.length === 1 ? compatible[0] : null };
    }),
    userMap: pf.users.map((u) => {
      const match = tenantUsers.find((tu) => tu.email.toLowerCase() === u.email.toLowerCase());
      return { sourceUserId: u.id, targetUserId: match?.id ?? null };
    }),
    teamMap: pf.teams.map((t) => ({ sourceTeamId: t.id, targetTeamId: null })),
    lifecycleMap: pf.lifecycles.map((label) => ({ sourceLabel: label, targetStatusId: null })),
  };
}

export interface CsvUploadState {
  fileName: string;
  rowCount: number;
}

export interface UseMigrationFormResult {
  form: UseFormReturn<MigrationFormValues>;
  connections: Connection[];
  workspaces: Workspace[];
  tenantUsers: User[];
  tenantTeams: Team[];
  preflight: MigrationPreflight | null;
  preflightLoading: boolean;
  compatibleTargetIds: (sourceValue: string) => string[];
  dryRunJob: MigrationJob | null;
  canStartMigration: boolean;
  ready: boolean;
  runDryRun: () => Promise<void>;
  startMigration: () => Promise<void>;
  submitting: boolean;
  contactsUpload: CsvUploadState | null;
  contactsCsvHeaders: string[];
  onContactsUploaded: (result: MigrationUploadResult, fileName: string) => void;
  onContactsCleared: () => void;
  snippetsUpload: CsvUploadState | null;
  onSnippetsUploaded: (result: MigrationUploadResult, fileName: string) => void;
  onSnippetsCleared: () => void;
}

export function useMigrationForm(): UseMigrationFormResult {
  const router = useRouter();
  const form = useForm<MigrationFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(migrationFormSchema),
    defaultValues: EMPTY_MIGRATION_FORM_VALUES,
  });

  const [connections, setConnections] = useState<Connection[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [tenantUsers, setTenantUsers] = useState<User[]>([]);
  const [tenantTeams, setTenantTeams] = useState<Team[]>([]);
  const [preflight, setPreflight] = useState<MigrationPreflight | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [dryRunJob, setDryRunJob] = useState<MigrationJob | null>(null);
  const [dryRunHash, setDryRunHash] = useState<string | null>(null);
  const [dryRunAt, setDryRunAt] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [contactsUpload, setContactsUpload] = useState<CsvUploadState | null>(null);
  const [contactsCsvHeaders, setContactsCsvHeaders] = useState<string[]>([]);
  const [snippetsUpload, setSnippetsUpload] = useState<CsvUploadState | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    integrationService
      .list({ page: 0, pageSize: 100 })
      .then((res) => setConnections(res.data.filter((c) => c.provider === 'respondio')))
      .catch(() => setConnections([]));
    workspaceService
      .list({ page: 0, pageSize: 100 })
      .then((res) => setWorkspaces(res.data.filter((w) => !w.isTrashed)))
      .catch(() => setWorkspaces([]));
    userService
      .list({ page: 0, pageSize: 200 })
      .then((res) => setTenantUsers(res.data))
      .catch(() => setTenantUsers([]));
    teamService
      .list({ page: 0, pageSize: 200 })
      .then((res) => setTenantTeams(res.data))
      .catch(() => setTenantTeams([]));
  }, []);

  const source = useWatch({ control: form.control, name: 'source' }) ?? 'api';
  const connectionId = useWatch({ control: form.control, name: 'connectionId' }) ?? null;
  const workspaceId = useWatch({ control: form.control, name: 'workspaceId' }) ?? '';

  // CSV mode has no preflight-derived space data at all - clear any stale
  // API-mode state so the Channels/People/Lifecycle sections (all guarded on
  // `!preflight`) stay hidden and the mapping hash never carries a ghost
  // mapping from a mode the operator switched away from.
  useEffect(() => {
    if (source === 'csv') {
      setPreflight(null);
      form.setValue('channelMap', [], { shouldDirty: true });
      form.setValue('userMap', [], { shouldDirty: true });
      form.setValue('teamMap', [], { shouldDirty: true });
      form.setValue('lifecycleMap', [], { shouldDirty: true });
    } else {
      setContactsUpload(null);
      setContactsCsvHeaders([]);
      form.setValue('contactsCsvKey', null, { shouldDirty: true });
      form.setValue('csvHeaderMap', {}, { shouldDirty: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  useEffect(() => {
    if (source !== 'api' || !connectionId || !workspaceId) {
      if (source !== 'api') setPreflight(null);
      return;
    }
    let active = true;
    setPreflightLoading(true);
    respondioMigrationService
      .preflight(connectionId, workspaceId)
      .then((pf) => {
        if (!active) return;
        setPreflight(pf);
        setDryRunJob(null);
        setDryRunHash(null);
        setDryRunAt(null);
        const seeded = seedFromPreflight(pf, tenantUsers);
        form.setValue('channelMap', seeded.channelMap ?? [], { shouldDirty: true });
        form.setValue('userMap', seeded.userMap ?? [], { shouldDirty: true });
        form.setValue('teamMap', seeded.teamMap ?? [], { shouldDirty: true });
        form.setValue('lifecycleMap', seeded.lifecycleMap ?? [], { shouldDirty: true });
      })
      .catch(() => active && setPreflight(null))
      .finally(() => active && setPreflightLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, connectionId, workspaceId]);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const pollDryRun = useCallback(
    (jobId: string) => {
      const tick = async () => {
        try {
          const job = await respondioMigrationService.getJob(jobId);
          setDryRunJob(job);
          if (job.status === 'done') {
            setDryRunAt(Date.now());
          }
          if (MIGRATION_JOB_IN_FLIGHT.has(job.status)) {
            pollTimer.current = setTimeout(tick, POLL_MS);
          }
        } catch {
          stopPolling();
        }
      };
      void tick();
    },
    [stopPolling],
  );

  const runDryRun = useCallback(async () => {
    const valid = await form.trigger();
    if (!valid) {
      toast.error('Please fix the highlighted fields.');
      return;
    }
    setSubmitting(true);
    try {
      const values = form.getValues();
      const input = toCreateMigrationJobInput(values, 'dry_run');
      const job = await respondioMigrationService.createJob(input);
      setDryRunJob(job);
      setDryRunHash(computeMappingHash(input));
      setDryRunAt(null);
      stopPolling();
      pollDryRun(job.id);
      toast.success('Dry run started.');
    } catch (error) {
      if (!applyFieldErrors(form, error)) toast.error(describe(error));
    } finally {
      setSubmitting(false);
    }
  }, [form, pollDryRun, stopPolling]);

  // `useWatch` without a `name` types its return as a deep-partial mirror of
  // the form - a structural TS artifact only (RHF's `defaultValues` already
  // guarantees every array/field is populated at mount); the merge below
  // exists purely to satisfy that type, not to patch real gaps.
  const watchedValues = useWatch({ control: form.control }) as MigrationFormValues;
  const liveHash = computeMappingHash(
    toCreateMigrationJobInput({ ...EMPTY_MIGRATION_FORM_VALUES, ...watchedValues }, 'run'),
  );
  const canStartMigration =
    !!dryRunJob &&
    dryRunJob.status === 'done' &&
    dryRunHash === liveHash &&
    dryRunAt !== null &&
    Date.now() - dryRunAt < 24 * 3_600_000;

  const ready =
    !!workspaceId && (source === 'api' ? !!connectionId && !preflightLoading : !!watchedValues.contactsCsvKey);

  const startMigration = useCallback(async () => {
    if (!canStartMigration) return;
    setSubmitting(true);
    try {
      const input = toCreateMigrationJobInput(form.getValues(), 'run');
      const job = await respondioMigrationService.createJob(input);
      toast.success('Migration started.');
      router.push(migrationJobPath(job.id));
    } catch (error) {
      if (!applyFieldErrors(form, error)) toast.error(describe(error));
    } finally {
      setSubmitting(false);
    }
  }, [canStartMigration, form, router]);

  const onContactsUploaded = useCallback(
    (result: MigrationUploadResult, fileName: string) => {
      setContactsUpload({ fileName, rowCount: result.rowCount });
      setContactsCsvHeaders(result.headers);
      form.setValue('contactsCsvKey', result.key, { shouldDirty: true });
      form.setValue('csvHeaderMap', {}, { shouldDirty: true });
      form.clearErrors('contactsCsvKey');
    },
    [form],
  );

  const onContactsCleared = useCallback(() => {
    setContactsUpload(null);
    setContactsCsvHeaders([]);
    form.setValue('contactsCsvKey', null, { shouldDirty: true });
    form.setValue('csvHeaderMap', {}, { shouldDirty: true });
  }, [form]);

  const onSnippetsUploaded = useCallback(
    (result: MigrationUploadResult, fileName: string) => {
      setSnippetsUpload({ fileName, rowCount: result.rowCount });
      form.setValue('snippetsCsvKey', result.key, { shouldDirty: true });
    },
    [form],
  );

  const onSnippetsCleared = useCallback(() => {
    setSnippetsUpload(null);
    form.setValue('snippetsCsvKey', null, { shouldDirty: true });
  }, [form]);

  return {
    form,
    connections,
    workspaces,
    tenantUsers,
    tenantTeams,
    preflight,
    preflightLoading,
    compatibleTargetIds: (sourceValue: string) => (preflight ? compatibleTargetIds(sourceValue, preflight) : []),
    dryRunJob,
    canStartMigration,
    ready,
    runDryRun,
    startMigration,
    submitting,
    contactsUpload,
    contactsCsvHeaders,
    onContactsUploaded,
    onContactsCleared,
    snippetsUpload,
    onSnippetsUploaded,
    onSnippetsCleared,
  };
}
