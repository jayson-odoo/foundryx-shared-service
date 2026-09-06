'use client';

/**
 * New-migration setup view (AC-MIG-03) - a `ResourceForm` (never a bespoke
 * wizard) whose ONE tab stacks the seven ordered sections. Create-only (no
 * existing job is ever re-opened here): `editable`/`initialEditing` start
 * true, mirroring `broadcast-form-view.tsx`'s `new/page.tsx` usage.
 */
import { useMemo } from 'react';
import { useWatch } from 'react-hook-form';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { ResourceForm, type FormTab } from '@/components/platform/resource-form';
import { useMigrationForm } from './use-migration-form';
import {
  ChannelsSection,
  LifecycleSection,
  PeopleSection,
  ReviewSection,
  ScopeSection,
  SourceSection,
  TargetSection,
} from './migration-form-sections';
import { migrationListPath } from './paths';

function SetupSections({ hook, editing }: { hook: ReturnType<typeof useMigrationForm>; editing: boolean }) {
  const { control, setValue, formState } = hook.form;
  const connectionId = useWatch({ control, name: 'connectionId' }) ?? '';
  const workspaceId = useWatch({ control, name: 'workspaceId' }) ?? '';
  const channelMap = useWatch({ control, name: 'channelMap' }) ?? [];
  const userMap = useWatch({ control, name: 'userMap' }) ?? [];
  const teamMap = useWatch({ control, name: 'teamMap' }) ?? [];
  const lifecycleMap = useWatch({ control, name: 'lifecycleMap' }) ?? [];
  const contactsOnly = useWatch({ control, name: 'contactsOnly' }) ?? false;
  const messagesSince = useWatch({ control, name: 'messagesSince' }) ?? null;

  return (
    <div className="flex flex-col gap-4">
      <SourceSection
        connections={hook.connections}
        value={connectionId}
        editing={editing}
        onChange={(v) => setValue('connectionId', v, { shouldDirty: true })}
        error={formState.errors.connectionId?.message}
      />
      <TargetSection
        workspaces={hook.workspaces}
        value={workspaceId}
        editing={editing}
        onChange={(v) => setValue('workspaceId', v, { shouldDirty: true })}
        error={formState.errors.workspaceId?.message}
      />
      <ChannelsSection
        preflight={hook.preflight}
        compatibleTargetIds={hook.compatibleTargetIds}
        value={channelMap}
        editing={editing}
        onChange={(next) => setValue('channelMap', next, { shouldDirty: true })}
      />
      <PeopleSection
        preflight={hook.preflight}
        tenantUsers={hook.tenantUsers}
        tenantTeams={hook.tenantTeams}
        userMap={userMap}
        teamMap={teamMap}
        editing={editing}
        onUserMapChange={(next) => setValue('userMap', next, { shouldDirty: true })}
        onTeamMapChange={(next) => setValue('teamMap', next, { shouldDirty: true })}
      />
      <LifecycleSection
        preflight={hook.preflight}
        value={lifecycleMap}
        editing={editing}
        onChange={(next) => setValue('lifecycleMap', next, { shouldDirty: true })}
      />
      <ScopeSection
        contactsOnly={contactsOnly}
        messagesSince={messagesSince}
        editing={editing}
        onChange={(next) => {
          setValue('contactsOnly', next.contactsOnly, { shouldDirty: true });
          setValue('messagesSince', next.messagesSince, { shouldDirty: true });
        }}
      />
      <ReviewSection
        connectionId={connectionId}
        workspaceId={workspaceId}
        preflightLoading={hook.preflightLoading}
        dryRunJob={hook.dryRunJob}
        canStartMigration={hook.canStartMigration}
        submitting={hook.submitting}
        onRunDryRun={() => void hook.runDryRun()}
        onStartMigration={() => void hook.startMigration()}
      />
    </div>
  );
}

export function MigrationFormView() {
  const hook = useMigrationForm();

  const config = useMemo(
    () => ({
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Omnichannel', href: migrationListPath },
        { label: 'Migration', href: migrationListPath },
        { label: 'New migration' },
      ],
      backHref: migrationListPath,
      backLabel: 'Back to migration',
      title: 'New migration',
      subtitle: 'Map a respond.io space onto a Foundryx workspace',
      tabs: [
        {
          id: 'setup',
          label: 'Setup',
          render: ({ editing }: { editing: boolean }) => <SetupSections hook={hook} editing={editing} />,
        } satisfies FormTab,
      ],
      actions: [],
      actionRows: [],
      editable: true,
      editPermission: 'omnichannel_migration.manage',
      initialEditing: true,
      isDirty: hook.form.formState.isDirty,
      // The shell's own Save button runs the SAME action as the Review
      // section's "Run dry run" (there is no separate "draft" entity to
      // save - a migration job IS the persisted record, plan §2). Always
      // returns false so the shell never flips `editing` off - a dry run
      // is a side-effect, not a save the setup form graduates out of; the
      // operator keeps editing the SAME mapping through to Start migration.
      onSave: async () => {
        await hook.runDryRun();
        return false;
      },
      onCancel: () => hook.form.reset(),
      entityNoun: 'migration',
    }),
    [hook],
  );

  return (
    <Container width="fluid">
      <Form {...hook.form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
