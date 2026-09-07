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
  const source = useWatch({ control, name: 'source' }) ?? 'api';
  const connectionId = useWatch({ control, name: 'connectionId' }) ?? null;
  const workspaceId = useWatch({ control, name: 'workspaceId' }) ?? '';
  const channelMap = useWatch({ control, name: 'channelMap' }) ?? [];
  const userMap = useWatch({ control, name: 'userMap' }) ?? [];
  const teamMap = useWatch({ control, name: 'teamMap' }) ?? [];
  const lifecycleMap = useWatch({ control, name: 'lifecycleMap' }) ?? [];
  const contactsOnly = useWatch({ control, name: 'contactsOnly' }) ?? false;
  const messagesSince = useWatch({ control, name: 'messagesSince' }) ?? null;
  const csvHeaderMap = useWatch({ control, name: 'csvHeaderMap' }) ?? {};

  return (
    <div className="flex flex-col gap-4">
      <SourceSection
        source={source}
        onSourceChange={(v) => setValue('source', v, { shouldDirty: true })}
        connections={hook.connections}
        connectionId={connectionId}
        onConnectionChange={(v) => setValue('connectionId', v, { shouldDirty: true })}
        connectionError={formState.errors.connectionId?.message}
        preflight={hook.preflight}
        preflightLoading={hook.preflightLoading}
        contactsUpload={hook.contactsUpload}
        contactsCsvHeaders={hook.contactsCsvHeaders}
        contactsCsvError={formState.errors.contactsUploadId?.message}
        onContactsUploaded={hook.onContactsUploaded}
        onContactsCleared={hook.onContactsCleared}
        csvHeaderMap={csvHeaderMap}
        onCsvHeaderMapChange={(next) => setValue('csvHeaderMap', next, { shouldDirty: true })}
        snippetsUpload={hook.snippetsUpload}
        onSnippetsUploaded={hook.onSnippetsUploaded}
        onSnippetsCleared={hook.onSnippetsCleared}
        editing={editing}
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
      {source === 'api' && (
        <ScopeSection
          contactsOnly={contactsOnly}
          messagesSince={messagesSince}
          editing={editing}
          onChange={(next) => {
            setValue('contactsOnly', next.contactsOnly, { shouldDirty: true });
            setValue('messagesSince', next.messagesSince, { shouldDirty: true });
          }}
        />
      )}
      <ReviewSection
        ready={hook.ready}
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
      // S6 fix (white-label hard-fail, PRINCIPLES.md): a tenant-facing string
      // never says "Foundryx" - the S0 subtitle did, undetected until this
      // slice's live E2E run against a real tenant actually rendered it.
      subtitle: 'Map a respond.io space onto a workspace',
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
