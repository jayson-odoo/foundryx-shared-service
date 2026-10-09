'use client';

/**
 * Setup form sections (AC-MIG-03..07) - Source / Target / Channels / People
 * / Lifecycle / Scope / Review, rendered as grouped Cards stacked in ONE
 * tab (the `broadcast-form-sections.tsx` pattern). Each source-side row is
 * pre-seeded 1:1 from the preflight response (`use-migration-form.tsx`)
 * and can never be added to or removed from - only its target changes.
 */
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { LoaderCircle } from 'lucide-react';
import { SearchSelect } from '@/components/platform/search-select';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { utcToZonedInputValue, zonedTimeToUtc } from '@/lib/datetime';
import { contactsListPath } from '@/app/(protected)/omnichannel/contacts/components/paths';
import type { Connection } from '@/types/integration';
import type { Workspace } from '@/types/omnichannel';
import type { Team } from '@/types/team';
import type { User } from '@/types/user';
import type {
  MigrationJob,
  MigrationPreflight,
  MigrationChannelMapEntry,
  MigrationUserMapEntry,
  MigrationTeamMapEntry,
  MigrationLifecycleMapEntry,
  MigrationSourceKind,
} from '@/types/respondio-migration';
import { ChannelMapRow } from './channel-map-row';
import { UserMapRow } from './user-map-row';
import { LifecycleMapRow } from './lifecycle-map-row';
import { MigrationReportCard } from './migration-report-card';
import { MIGRATION_STATUS_REGISTRY } from './migration-status';
import { CsvUploadField } from './csv-upload-field';
import { CsvHeaderMapSection } from './csv-header-map-section';
import type { CsvUploadState } from './use-migration-form';
import type { MigrationUploadResult } from '@/types/respondio-migration';

const SOURCE_KIND_OPTIONS = [
  { label: 'respond.io Developer API', value: 'api' },
  { label: 'CSV export', value: 'csv' },
];

export function SourceSection({
  source,
  onSourceChange,
  connections,
  connectionId,
  onConnectionChange,
  connectionError,
  preflight,
  preflightLoading,
  contactsUpload,
  contactsCsvHeaders,
  contactsCsvError,
  onContactsUploaded,
  onContactsCleared,
  csvHeaderMap,
  onCsvHeaderMapChange,
  snippetsUpload,
  onSnippetsUploaded,
  onSnippetsCleared,
  editing,
}: {
  source: MigrationSourceKind;
  onSourceChange: (next: MigrationSourceKind) => void;
  connections: Connection[];
  connectionId: string | null;
  onConnectionChange: (id: string) => void;
  connectionError?: string;
  preflight: MigrationPreflight | null;
  preflightLoading: boolean;
  contactsUpload: CsvUploadState | null;
  contactsCsvHeaders: string[];
  contactsCsvError?: string;
  onContactsUploaded: (result: MigrationUploadResult, fileName: string) => void;
  onContactsCleared: () => void;
  csvHeaderMap: Record<string, string>;
  onCsvHeaderMapChange: (next: Record<string, string>) => void;
  snippetsUpload: CsvUploadState | null;
  onSnippetsUploaded: (result: MigrationUploadResult, fileName: string) => void;
  onSnippetsCleared: () => void;
  editing: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Source</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 py-4">
        <div className="max-w-sm space-y-1.5">
          <label className="text-sm text-muted-foreground">Method</label>
          <SearchSelect
            ariaLabel="Migration source method"
            options={SOURCE_KIND_OPTIONS}
            value={source}
            onChange={(v) => onSourceChange(v as MigrationSourceKind)}
            disabled={!editing}
          />
        </div>

        {source === 'api' ? (
          <div className="max-w-sm space-y-1.5">
            <label className="text-sm text-muted-foreground">respond.io connection *</label>
            <SearchSelect
              ariaLabel="respond.io connection"
              options={connections.map((c) => ({ label: c.name, value: c.id }))}
              value={connectionId}
              onChange={onConnectionChange}
              disabled={!editing}
            />
            {connectionError && <p className="text-destructive text-xs">{connectionError}</p>}
            {preflightLoading && (
              <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
                <LoaderCircle className="size-3 animate-spin" /> Checking the connection…
              </p>
            )}
            {!preflightLoading && preflight && (preflight.warnings.length > 0 || !preflight.apiAvailable) && (
              <ul className="space-y-1 pt-1">
                {(preflight.warnings.length > 0
                  ? preflight.warnings
                  : ['Could not reach respond.io with this connection.']
                ).map((w, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <Badge
                      variant={preflight.apiAvailable ? 'warning' : 'destructive'}
                      appearance="light"
                      size="sm"
                      className="mt-0.5 shrink-0"
                    >
                      {preflight.apiAvailable ? 'Notice' : 'Blocked'}
                    </Badge>
                    <ClampedText text={w} lines={2} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="max-w-md space-y-5">
            <CsvUploadField
              kind="contacts"
              label="Contacts CSV *"
              editing={editing}
              fileName={contactsUpload?.fileName ?? null}
              rowCount={contactsUpload?.rowCount ?? null}
              onUploaded={onContactsUploaded}
              onClear={onContactsCleared}
              error={contactsCsvError}
            />
            <CsvHeaderMapSection
              headers={contactsCsvHeaders}
              value={csvHeaderMap}
              editing={editing}
              onChange={onCsvHeaderMapChange}
            />
            <Button type="button" variant="outline" size="sm" asChild>
              <Link href={contactsListPath}>Import contacts</Link>
            </Button>
          </div>
        )}

        <div className="max-w-md">
          <CsvUploadField
            kind="snippets"
            label="Quick replies CSV"
            editing={editing}
            fileName={snippetsUpload?.fileName ?? null}
            rowCount={snippetsUpload?.rowCount ?? null}
            onUploaded={onSnippetsUploaded}
            onClear={onSnippetsCleared}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export function TargetSection({
  workspaces,
  value,
  editing,
  onChange,
  error,
}: {
  workspaces: Workspace[];
  value: string;
  editing: boolean;
  onChange: (id: string) => void;
  error?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Target</CardTitle>
      </CardHeader>
      <CardContent className="py-4">
        <div className="max-w-sm space-y-1.5">
          <label className="text-sm text-muted-foreground">Target workspace *</label>
          <SearchSelect
            ariaLabel="Target workspace"
            options={workspaces.map((w) => ({ label: w.name, value: w.id }))}
            value={value || null}
            onChange={onChange}
            disabled={!editing}
          />
          {error && <p className="text-destructive text-xs">{error}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

export function ChannelsSection({
  preflight,
  compatibleTargetIds,
  value,
  editing,
  onChange,
}: {
  preflight: MigrationPreflight | null;
  compatibleTargetIds: (sourceValue: string) => string[];
  value: MigrationChannelMapEntry[];
  editing: boolean;
  onChange: (next: MigrationChannelMapEntry[]) => void;
}) {
  if (!preflight) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Channels</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 py-4">
        {preflight.channels.map((channel) => {
          const entry = value.find((e) => e.sourceChannelId === channel.id);
          const compatible = compatibleTargetIds(channel.source)
            .map((id) => preflight.targetChannels.find((t) => t.id === id))
            .filter((t): t is NonNullable<typeof t> => !!t);
          return (
            <ChannelMapRow
              key={channel.id}
              channel={channel}
              compatibleTargets={compatible}
              value={entry?.targetChannelId ?? null}
              editing={editing}
              onChange={(targetChannelId) =>
                onChange(value.map((e) => (e.sourceChannelId === channel.id ? { ...e, targetChannelId } : e)))
              }
            />
          );
        })}
      </CardContent>
    </Card>
  );
}

export function PeopleSection({
  preflight,
  tenantUsers,
  tenantTeams,
  userMap,
  teamMap,
  editing,
  onUserMapChange,
  onTeamMapChange,
}: {
  preflight: MigrationPreflight | null;
  tenantUsers: User[];
  tenantTeams: Team[];
  userMap: MigrationUserMapEntry[];
  teamMap: MigrationTeamMapEntry[];
  editing: boolean;
  onUserMapChange: (next: MigrationUserMapEntry[]) => void;
  onTeamMapChange: (next: MigrationTeamMapEntry[]) => void;
}) {
  if (!preflight) return null;
  const userOptions = tenantUsers.map((u) => ({ label: u.name ?? u.email, value: u.id }));
  const teamOptions = tenantTeams.map((t) => ({ label: t.name, value: t.id }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>People</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 py-4">
        {preflight.users.length > 0 && (
          <div className="space-y-3">
            <p className="text-sm font-medium">Agents</p>
            {preflight.users.map((u) => {
              const entry = userMap.find((e) => e.sourceUserId === u.id);
              return (
                <UserMapRow
                  key={u.id}
                  label={`${u.firstName} ${u.lastName}`.trim()}
                  sublabel={u.email}
                  options={userOptions}
                  value={entry?.targetUserId ?? null}
                  editing={editing}
                  ariaLabel={`Target user for ${u.firstName} ${u.lastName}`}
                  onChange={(targetUserId) =>
                    onUserMapChange(userMap.map((e) => (e.sourceUserId === u.id ? { ...e, targetUserId } : e)))
                  }
                />
              );
            })}
          </div>
        )}
        {preflight.teams.length > 0 && (
          <div className="space-y-3">
            <p className="text-sm font-medium">Teams</p>
            {preflight.teams.map((t) => {
              const entry = teamMap.find((e) => e.sourceTeamId === t.id);
              return (
                <UserMapRow
                  key={t.id}
                  label={t.name}
                  options={teamOptions}
                  value={entry?.targetTeamId ?? null}
                  editing={editing}
                  ariaLabel={`Target team for ${t.name}`}
                  onChange={(targetTeamId) =>
                    onTeamMapChange(teamMap.map((e) => (e.sourceTeamId === t.id ? { ...e, targetTeamId } : e)))
                  }
                />
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function LifecycleSection({
  preflight,
  value,
  editing,
  onChange,
}: {
  preflight: MigrationPreflight | null;
  value: MigrationLifecycleMapEntry[];
  editing: boolean;
  onChange: (next: MigrationLifecycleMapEntry[]) => void;
}) {
  if (!preflight || preflight.lifecycles.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Lifecycle</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 py-4">
        {preflight.lifecycles.map((sourceLabel) => {
          const entry = value.find((e) => e.sourceLabel === sourceLabel);
          return (
            <LifecycleMapRow
              key={sourceLabel}
              sourceLabel={sourceLabel}
              targetStages={preflight.targetStages}
              value={entry?.targetStatusId ?? null}
              editing={editing}
              onChange={(targetStatusId) =>
                onChange(value.map((e) => (e.sourceLabel === sourceLabel ? { ...e, targetStatusId } : e)))
              }
            />
          );
        })}
      </CardContent>
    </Card>
  );
}

export function ScopeSection({
  contactsOnly,
  messagesSince,
  editing,
  onChange,
}: {
  contactsOnly: boolean;
  messagesSince: string | null;
  editing: boolean;
  onChange: (next: { contactsOnly: boolean; messagesSince: string | null }) => void;
}) {
  // `messagesSince` is a FLOOR on the operator's own calendar day, converted
  // through their timezone preference (`zonedTimeToUtc`) rather than treated
  // as UTC midnight - a `<input type="date">` value has no timezone of its
  // own, and reading it as UTC would silently shift the floor by a day near
  // a timezone boundary (`lib/datetime.ts`, the `useDatetime()` mandate).
  const { timeZone } = useDatetime();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scope</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm">Contacts only (skip message history)</span>
          <Switch
            checked={contactsOnly}
            disabled={!editing}
            onCheckedChange={(checked) => onChange({ contactsOnly: checked, messagesSince })}
          />
        </div>
        <div className="max-w-xs space-y-1.5">
          <label className="text-sm text-muted-foreground">Messages since</label>
          <Input
            type="date"
            aria-label="Messages since"
            value={messagesSince ? utcToZonedInputValue(messagesSince, timeZone).slice(0, 10) : ''}
            disabled={!editing || contactsOnly}
            onChange={(e) => {
              const v = e.target.value;
              const utc = v ? zonedTimeToUtc(`${v}T00:00`, timeZone) : null;
              onChange({ contactsOnly, messagesSince: utc ? utc.toISOString() : null });
            }}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export function ReviewSection({
  ready,
  dryRunJob,
  canStartMigration,
  submitting,
  onRunDryRun,
  onStartMigration,
}: {
  ready: boolean;
  dryRunJob: MigrationJob | null;
  canStartMigration: boolean;
  submitting: boolean;
  onRunDryRun: () => void;
  onStartMigration: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Review</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 py-4">
        {dryRunJob && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Dry run:</span>
            <StatusBadge status={dryRunJob.status} registry={MIGRATION_STATUS_REGISTRY} size="sm" />
            {(dryRunJob.status === 'pending' || dryRunJob.status === 'running') && (
              <LoaderCircle className="text-muted-foreground size-4 animate-spin" />
            )}
          </div>
        )}
        {dryRunJob?.report && <MigrationReportCard report={dryRunJob.report} />}
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={onRunDryRun} disabled={!ready || submitting}>
            Run dry run
          </Button>
          <Button type="button" variant="outline" onClick={onStartMigration} disabled={!canStartMigration || submitting}>
            Start migration
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
