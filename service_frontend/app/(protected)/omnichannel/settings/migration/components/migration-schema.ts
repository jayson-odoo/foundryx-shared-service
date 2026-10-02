import { z } from 'zod';
import type { CreateMigrationJobInput, MigrationMode } from '@/types/respondio-migration';

// Re-exported so every file in this feature imports the hash from ONE place
// (the schema is the natural "form contract" home; the function itself
// lives in `types/respondio-migration.ts` so the mock SERVICE can share it
// without importing across the app/ route tree, plan §3 D-A6-14).
export { computeMappingHash } from '@/types/respondio-migration';

const channelMapEntrySchema = z.object({
  sourceChannelId: z.string().min(1),
  targetChannelId: z.string().nullable(),
});
const userMapEntrySchema = z.object({
  sourceUserId: z.string().min(1),
  targetUserId: z.string().nullable(),
});
const teamMapEntrySchema = z.object({
  sourceTeamId: z.string().min(1),
  targetTeamId: z.string().nullable(),
});
const lifecycleMapEntrySchema = z.object({
  sourceLabel: z.string().min(1),
  targetStatusId: z.string().nullable(),
});

/**
 * The setup form's RHF contract (AC-MIG-58 "the setup form schema" +
 * "channel map completeness"). `channelMap` must cover every discovered
 * source channel (Review can't be reached with a partially-mapped list -
 * the form seeds the array 1:1 from the preflight response and never lets
 * a row be removed, so "completeness" reduces to "non-empty AND loaded from
 * a preflight", checked here as a length guard) - API MODE ONLY: CSV mode
 * (S5/S6, D-A6-25) has no preflight-derived channel/user/team/lifecycle rows
 * at all, so `channelMap` stays legitimately empty there.
 */
export const migrationFormSchema = z
  .object({
    connectionId: z.string().nullable(),
    workspaceId: z.string().min(1, 'Choose a target workspace.'),
    source: z.enum(['api', 'csv']),
    channelMap: z.array(channelMapEntrySchema),
    userMap: z.array(userMapEntrySchema),
    teamMap: z.array(teamMapEntrySchema),
    lifecycleMap: z.array(lifecycleMapEntrySchema),
    messagesSince: z.string().nullable(),
    contactsOnly: z.boolean(),
    contactsUploadId: z.string().nullable(),
    csvHeaderMap: z.record(z.string(), z.string()),
    snippetsUploadId: z.string().nullable(),
  })
  .superRefine((value, ctx) => {
    if (value.source === 'api') {
      if (!value.connectionId) {
        ctx.addIssue({ code: 'custom', message: 'Choose a connection.', path: ['connectionId'] });
      }
      if (value.channelMap.length === 0) {
        ctx.addIssue({ code: 'custom', message: 'Run preflight to load the source channels.', path: ['channelMap'] });
      }
    } else if (!value.contactsUploadId) {
      ctx.addIssue({ code: 'custom', message: 'Upload a contacts CSV.', path: ['contactsUploadId'] });
    }
  });

export type MigrationFormValues = z.infer<typeof migrationFormSchema>;

export const EMPTY_MIGRATION_FORM_VALUES: MigrationFormValues = {
  connectionId: null,
  workspaceId: '',
  source: 'api',
  channelMap: [],
  userMap: [],
  teamMap: [],
  lifecycleMap: [],
  messagesSince: null,
  contactsOnly: false,
  contactsUploadId: null,
  csvHeaderMap: {},
  snippetsUploadId: null,
};

export function toCreateMigrationJobInput(
  values: MigrationFormValues,
  mode: MigrationMode,
): CreateMigrationJobInput {
  return {
    connectionId: values.connectionId,
    workspaceId: values.workspaceId,
    mode,
    source: values.source,
    channelMap: values.channelMap,
    userMap: values.userMap,
    teamMap: values.teamMap,
    lifecycleMap: values.lifecycleMap,
    messagesSince: values.messagesSince,
    contactsOnly: values.contactsOnly,
    contactsUploadId: values.contactsUploadId,
    csvHeaderMap: values.csvHeaderMap,
    snippetsUploadId: values.snippetsUploadId,
  };
}
