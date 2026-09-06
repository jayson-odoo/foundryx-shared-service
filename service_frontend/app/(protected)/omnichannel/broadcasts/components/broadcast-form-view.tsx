'use client';

/**
 * Broadcast builder + detail view (plan 29, AC-BRD-04/09/10). Create mode
 * renders ALL six sections stacked in one tab, ending in the Review
 * section's Test-send + Send/Schedule primary actions. Detail mode renders
 * the same sections read/edit (Overview tab, editable only while DRAFT) plus
 * an embedded Recipients `ResourceList` tab.
 */
import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import { LoaderCircleIcon, ListChecks, LayoutList } from 'lucide-react';
import { useWatch } from 'react-hook-form';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm, type FormTab } from '@/components/platform/resource-form';
import { ResourceList } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { useConversationSocket } from '@/hooks/use-conversation-socket';
import type { Broadcast, ConversationSocketEvent } from '@/types/omnichannel';
import { useBroadcastForm } from './use-broadcast-form';
import { useActiveChannels, useApprovedTemplates, ChannelSection, DetailsSection, MessageSectionHeader, PrimaryActionsRow, ReviewSummary, ScheduleSection, StatusSummary, TestSendDialog } from './broadcast-form-sections';
import { AudienceSection } from './audience-section';
import { BindingEditor } from './binding-editor';
import { matchBroadcastUpdate } from './broadcast-realtime';
import { useAudiencePreview } from './use-audience-preview';
import { useRecipientsListConfig } from './use-recipients-list-config';
import { broadcastFormSchema } from './broadcast-schema';
import { broadcastsListPath } from './paths';

function BuilderSections({
  workspaceId,
  editing,
  form,
  broadcast,
  creating,
  ensureDraftId,
  sendOrSchedule,
  sending,
}: {
  workspaceId: string | null;
  editing: boolean;
  form: ReturnType<typeof useBroadcastForm>['form'];
  broadcast: Broadcast | null;
  creating: boolean;
  ensureDraftId: () => Promise<string | null>;
  sendOrSchedule: () => Promise<void>;
  sending: boolean;
}) {
  const { control, setValue, formState } = form;
  const { can } = useCan();
  const [testOpen, setTestOpen] = useState(false);

  // Named single-field subscriptions (not a whole-object useWatch) so each
  // value keeps its EXACT field type - a whole-object watch on a form with a
  // discriminated-union field (audience/bindings) degrades to a deep-partial
  // type that loses the union discriminant.
  const name = useWatch({ control, name: 'name' }) ?? '';
  const labels = useWatch({ control, name: 'labels' }) ?? [];
  const channelId = useWatch({ control, name: 'channelId' }) ?? '';
  const audience = useWatch({ control, name: 'audience' }) ?? { kind: 'segment' as const };
  const templateId = useWatch({ control, name: 'templateId' }) ?? '';
  const bindings = useWatch({ control, name: 'bindings' }) ?? { header: [], body: [], buttons: [] };
  const scheduleMode = useWatch({ control, name: 'scheduleMode' }) ?? 'now';
  const scheduledAt = useWatch({ control, name: 'scheduledAt' }) ?? null;

  const channels = useActiveChannels(workspaceId);
  const selectedChannel = channels.find((c) => c.id === channelId) ?? null;
  const templates = useApprovedTemplates(channelId);
  const selectedTemplate = templates.find((t) => t.id === templateId) ?? null;
  const { count: audienceCount } = useAudiencePreview(workspaceId, audience);

  const canSend = can('broadcasts.send');
  const parsed = broadcastFormSchema.safeParse({
    name,
    labels,
    channelId,
    audience,
    templateId,
    bindings,
    scheduleMode,
    scheduledAt,
  });
  const canSubmit = parsed.success;

  return (
    <div className="flex flex-col gap-4">
      {!creating && broadcast && <StatusSummary broadcast={broadcast} />}

      <DetailsSection
        name={name}
        labels={labels}
        editing={editing}
        onNameChange={(v) => setValue('name', v, { shouldDirty: true, shouldTouch: true })}
        onLabelsChange={(v) => setValue('labels', v, { shouldDirty: true })}
        error={formState.errors.name?.message}
      />

      <AudienceSection
        workspaceId={workspaceId}
        editing={editing}
        value={audience}
        onChange={(next) => {
          setValue('audience', next, { shouldDirty: true });
        }}
      />

      <ChannelSection
        channels={channels}
        value={channelId}
        editing={editing}
        onChange={(next) => {
          setValue('channelId', next, { shouldDirty: true });
          // Changing the channel clears the template and its bindings (AC-BRD-06).
          setValue('templateId', '', { shouldDirty: true });
          setValue('bindings', { header: [], body: [], buttons: [] }, { shouldDirty: true });
        }}
        error={formState.errors.channelId?.message}
      />

      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="mb-3 text-base font-medium">Message</h3>
        <MessageSectionHeader
          templates={templates}
          templateId={templateId}
          editing={editing}
          onChange={(next) => {
            const tpl = templates.find((t) => t.id === next);
            setValue('templateId', next, { shouldDirty: true });
            setValue(
              'bindings',
              {
                header: Array.from({ length: tpl?.headerVariableCount ?? 0 }, () => ({
                  source: 'contactField' as const,
                  field: 'firstName',
                  fallback: '',
                })),
                body: Array.from({ length: tpl?.variableCount ?? 0 }, () => ({
                  source: 'contactField' as const,
                  field: 'firstName',
                  fallback: '',
                })),
                buttons: Array.from({ length: tpl?.buttonVariableCount ?? 0 }, () => ({
                  source: 'static' as const,
                  text: '',
                })),
              },
              { shouldDirty: true },
            );
          }}
          error={formState.errors.templateId?.message}
        />
        {selectedTemplate && (
          <div className="mt-3">
            <BindingEditor
              channelId={channelId}
              template={selectedTemplate}
              editing={editing}
              header={bindings.header}
              body={bindings.body}
              buttons={bindings.buttons}
              onChangeHeader={(next) => setValue('bindings.header', next, { shouldDirty: true })}
              onChangeBody={(next) => setValue('bindings.body', next, { shouldDirty: true })}
              onChangeButtons={(next) => setValue('bindings.buttons', next, { shouldDirty: true })}
            />
          </div>
        )}
      </div>

      <ScheduleSection
        scheduleMode={scheduleMode}
        scheduledAt={scheduledAt}
        editing={editing}
        onChange={(mode, at) => {
          setValue('scheduleMode', mode, { shouldDirty: true });
          setValue('scheduledAt', at, { shouldDirty: true });
        }}
        error={formState.errors.scheduledAt?.message}
      />

      <ReviewSummary
        values={{ name, labels, channelId, audience, templateId, bindings, scheduleMode, scheduledAt }}
        channelName={selectedChannel?.name ?? ''}
        templateName={selectedTemplate?.name ?? ''}
        audienceCount={audienceCount}
      />

      {/* AC-BRD-09/10: the primary Send/Schedule action lives on the Review
          section for as long as the broadcast is STILL Draft (a brand-new
          unsaved one OR a saved Draft revisited/duplicated) - "read-only"
          starts only once it has actually LEFT Draft. Plan §S0 originally
          gated this on `creating` alone, which stranded a saved Draft
          (e.g. a just-duplicated broadcast) with no way to Send/Schedule
          from this view at all - a real-data-only bug this slice fixes. */}
      {(creating || broadcast?.status === 'DRAFT') && editing && canSend && (
        <>
          <PrimaryActionsRow
            scheduleMode={scheduleMode}
            canSubmit={canSubmit}
            sending={sending}
            testDisabled={!channelId || !templateId}
            onTestSend={() => setTestOpen(true)}
            onSubmit={sendOrSchedule}
          />
          <TestSendDialog
            open={testOpen}
            onOpenChange={setTestOpen}
            workspaceId={workspaceId}
            ensureBroadcastId={ensureDraftId}
          />
        </>
      )}

      {!creating && broadcast && broadcast.status !== 'DRAFT' && canSend && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" onClick={() => setTestOpen(true)}>
              Send test message
            </Button>
          </div>
          <TestSendDialog
            open={testOpen}
            onOpenChange={setTestOpen}
            workspaceId={workspaceId}
            ensureBroadcastId={async () => broadcast.id}
          />
        </>
      )}
    </div>
  );
}

export interface BroadcastFormViewProps {
  workspaceId: string | null;
  broadcastId?: string;
  initialEditing: boolean;
}

export function BroadcastFormView({ workspaceId, broadcastId, initialEditing }: BroadcastFormViewProps) {
  const {
    config,
    form,
    isLoading,
    notFound,
    broadcast,
    creating,
    ensureDraftId,
    sendOrSchedule,
    sending,
    refresh,
  } = useBroadcastForm(workspaceId, broadcastId, initialEditing);

  const { config: recipientsConfig, reload: reloadRecipients, reloadToken } = useRecipientsListConfig(
    workspaceId,
    broadcast?.id ?? null,
  );

  // Plan 29 S4 (AC-BRD-13/45) - the broadcast's own status/counts AND its
  // Recipients tab update LIVE off the workspace socket while a send job is
  // running, no polling. `broadcast.updated` is best-effort (a dead Redis
  // never fails the send job) - a missed frame just means the next one (or
  // the tab's own remount) catches the surface up.
  const activeBroadcastId = broadcast?.id;
  const onSocketEvent = useCallback(
    (event: ConversationSocketEvent) => {
      if (!matchBroadcastUpdate(event, activeBroadcastId)) return;
      void refresh();
      reloadRecipients();
    },
    [activeBroadcastId, refresh, reloadRecipients],
  );
  useConversationSocket(workspaceId, onSocketEvent);

  const fullConfig = useMemo(() => {
    if (!config) return null;
    const overviewTab: FormTab = {
      id: 'overview',
      label: 'Overview',
      icon: LayoutList,
      render: ({ editing }) => (
        <BuilderSections
          workspaceId={workspaceId}
          editing={editing}
          form={form}
          broadcast={broadcast}
          creating={creating}
          ensureDraftId={ensureDraftId}
          sendOrSchedule={sendOrSchedule}
          sending={sending}
        />
      ),
    };
    if (creating) return { ...config, tabs: [overviewTab] };
    const recipientsTab: FormTab = {
      id: 'recipients',
      label: 'Recipients',
      icon: ListChecks,
      // Keyed on `reloadToken` (bumped by the `broadcast.updated` WS handler
      // above) - remounting is how every embedded `ResourceList` in this
      // codebase forces a refetch from outside (no external "refetch now"
      // prop on the shell; the Templates-tab precedent).
      render: () => <ResourceList key={reloadToken} config={recipientsConfig} hideHeader />,
    };
    return { ...config, tabs: [overviewTab, recipientsTab], initialTabId: 'overview' };
  }, [config, workspaceId, form, broadcast, creating, ensureDraftId, sendOrSchedule, sending, recipientsConfig, reloadToken]);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !fullConfig) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Broadcast not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={broadcastsListPath}>Back to broadcasts</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={fullConfig} />
      </Form>
    </Container>
  );
}
