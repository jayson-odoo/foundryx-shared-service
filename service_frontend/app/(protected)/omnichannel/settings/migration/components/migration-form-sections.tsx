'use client';

/**
 * Setup form sections (AC-MIG-03..07) - Source / Target / Channels / People
 * / Lifecycle / Scope / Review, rendered as grouped Cards stacked in ONE
 * tab (the `broadcast-form-sections.tsx` pattern). Each source-side row is
 * pre-seeded 1:1 from the preflight response (`use-migration-form.tsx`)
 * and can never be added to or removed from - only its target changes.
 */
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { LoaderCircle } from 'lucide-react';
import { SearchSelect } from '@/components/platform/search-select';
import { StatusBadge } from '@/components/platform/status-badge';
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
} from '@/types/respondio-migration';
import { ChannelMapRow } from './channel-map-row';
import { UserMapRow } from './user-map-row';
import { LifecycleMapRow } from './lifecycle-map-row';
import { MigrationReportCard } from './migration-report-card';
import { MIGRATION_STATUS_REGISTRY } from './migration-status';

export function SourceSection({
  connections,
  value,
  editing,
  onChange,
  error,
}: {
  connections: Connection[];
  value: string;
  editing: boolean;
  onChange: (id: string) => void;
  error?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Source</CardTitle>
      </CardHeader>
      <CardContent className="py-4">
        <div className="max-w-sm space-y-1.5">
          <label className="text-sm text-muted-foreground">respond.io connection *</label>
          <SearchSelect
            ariaLabel="respond.io connection"
            options={connections.map((c) => ({ label: c.name, value: c.id }))}
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
            value={messagesSince ? messagesSince.slice(0, 10) : ''}
            disabled={!editing || contactsOnly}
            onChange={(e) => {
              const v = e.target.value;
              onChange({ contactsOnly, messagesSince: v ? new Date(`${v}T00:00:00Z`).toISOString() : null });
            }}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export function ReviewSection({
  connectionId,
  workspaceId,
  preflightLoading,
  dryRunJob,
  canStartMigration,
  submitting,
  onRunDryRun,
  onStartMigration,
}: {
  connectionId: string;
  workspaceId: string;
  preflightLoading: boolean;
  dryRunJob: MigrationJob | null;
  canStartMigration: boolean;
  submitting: boolean;
  onRunDryRun: () => void;
  onStartMigration: () => void;
}) {
  const ready = !!connectionId && !!workspaceId && !preflightLoading;
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
