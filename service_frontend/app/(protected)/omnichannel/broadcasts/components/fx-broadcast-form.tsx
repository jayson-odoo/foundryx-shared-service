'use client';

/**
 * New broadcast under the Foundryx UIUX switch (playbook 0.71.0, slice
 * W1-BROADCAST, approved mock "New broadcast").
 *
 * - The same long form in today's order: Details, Audience, Channel,
 *   Message, Schedule, Review. Same fields, same rules (the same form hook,
 *   so Create, Save, Test send, Send now and Schedule send the same requests
 *   as the switch-off page).
 * - One red action at the top right, "Send now" or "Schedule broadcast",
 *   naming the send on hover ("Send now to 23 contacts with
 *   promo_nov_2026"); blocked with its reason while a required field is
 *   missing, pulsing that field. It sends at once, as today.
 * - Save as draft, Send a test message and Discard changes as icon actions.
 * - Schedule as a typed date, a time list (12-hour clock) and the zone line.
 * - After a send, the done page on the broadcast's own address (answers Q3).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { FlaskConical, Save } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { useWatch } from 'react-hook-form';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { PageHeader } from '@/components/platform/page-header';
import { SearchSelect } from '@/components/platform/search-select';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import { FxDiscardDialog } from '@/components/fx/actions/confirm-dialog';
import { useHideMainAction, useRegisterMainAction, type FxMainActionSpec } from '@/components/fx/actions/page-actions-context';
import { FxDateField, FxField, FxZoneLine } from '@/components/fx/fields';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { dateKey } from '@/lib/datetime';
import type { Broadcast } from '@/types/omnichannel';
import { useBroadcastForm } from './use-broadcast-form';
import {
  ChannelSection,
  DetailsSection,
  MessageSectionHeader,
  ReviewSummary,
  TestSendDialog,
  useActiveChannels,
  useApprovedTemplates,
} from './broadcast-form-sections';
import { AudienceSection } from './audience-section';
import { BindingEditor } from './binding-editor';
import { bindingSlotErrors } from './binding-slot-errors';
import { useAudiencePreview } from './use-audience-preview';
import { setBroadcastDone } from './broadcast-done-store';
import { broadcastFormPath, broadcastsListPath } from './paths';
import type { BroadcastFormValues } from './broadcast-schema';
import {
  BC_PULSE,
  broadcastBlocked,
  broadcastMainLabels,
  joinScheduledAt,
  splitScheduledAt,
  timeOptions,
  type ScheduleParts,
} from './fx-broadcast-actions';

/** Schedule: Send now | Schedule for, then a typed date, a time list and the zone. */
function FxScheduleSection({
  scheduleMode,
  parts,
  timeZone,
  onMode,
  onParts,
}: {
  scheduleMode: BroadcastFormValues['scheduleMode'];
  parts: ScheduleParts;
  timeZone: string;
  onMode: (mode: BroadcastFormValues['scheduleMode']) => void;
  onParts: (next: ScheduleParts) => void;
}) {
  const today = dateKey(new Date(), { timeZone }) ?? undefined;
  return (
    <section className="flex flex-col gap-4 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-5">
      <h2 className="text-base font-bold text-(--fx-ink)">Schedule</h2>
      <ToggleGroup
        type="single"
        value={scheduleMode}
        onValueChange={(v) => {
          if (v === 'now' || v === 'schedule') onMode(v);
        }}
        aria-label="When to send"
        className="self-start"
      >
        <ToggleGroupItem value="now">Send now</ToggleGroupItem>
        <ToggleGroupItem value="schedule">Schedule for</ToggleGroupItem>
      </ToggleGroup>
      {scheduleMode === 'schedule' && (
        <div className="flex flex-col gap-2">
          <div className="grid max-w-[520px] gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="bc-schedule-date" className="text-sm font-semibold text-(--fx-ink-2)">
                Date
              </label>
              <div data-fx-pulse-target={BC_PULSE.date}>
                <FxDateField
                  id="bc-schedule-date"
                  value={parts.date}
                  onChange={(date) => onParts({ ...parts, date })}
                  timeZone={timeZone}
                  minDate={today}
                  placeholder="20 Nov 2026"
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-semibold text-(--fx-ink-2)">Time</span>
              <FxField>
                <div data-fx-pulse-target={BC_PULSE.time}>
                  <SearchSelect
                    options={timeOptions(parts.time)}
                    value={parts.time}
                    onChange={(time) => onParts({ ...parts, time })}
                    ariaLabel="Time"
                    className="w-full"
                  />
                </div>
              </FxField>
            </div>
          </div>
          <FxZoneLine />
        </div>
      )}
    </section>
  );
}

export interface FxBroadcastFormViewProps {
  workspaceId: string | null;
}

export function FxBroadcastFormView({ workspaceId }: FxBroadcastFormViewProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const byWhom = session?.user?.name ?? null;
  const audienceAtSend = useRef<number | null>(null);

  const onSent = useCallback(
    (sent: Broadcast, mode: BroadcastFormValues['scheduleMode']) => {
      setBroadcastDone(sent.id, {
        mode,
        byWhom,
        audienceCount: audienceAtSend.current,
        pressedAt: new Date().toISOString(),
      });
      router.push(broadcastFormPath(sent.id));
    },
    [byWhom, router],
  );
  const hookOptions = useMemo(() => ({ onSent }), [onSent]);
  const { config, form, ensureDraftId, sendOrSchedule, sending } = useBroadcastForm(
    workspaceId,
    undefined,
    true,
    hookOptions,
  );
  const { control, setValue, formState } = form;
  const { can } = useCan();
  const canSend = can('broadcasts.send');
  const { timeZone, formatDateTime } = useDatetime();

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

  const [parts, setParts] = useState<ScheduleParts>(() => splitScheduledAt(scheduledAt, timeZone));
  const [testOpen, setTestOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  useHideMainAction(testOpen);

  const isDirty = formState.isDirty;
  // Warn on a browser-level leave while there are unsaved edits (as today).
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const values: BroadcastFormValues = {
    name,
    labels,
    channelId,
    audience,
    templateId,
    bindings,
    scheduleMode,
    scheduledAt,
  };
  const blocked = broadcastBlocked(values, parts);
  const { label, fullLabel } = broadcastMainLabels({
    mode: scheduleMode,
    audienceCount,
    templateName: selectedTemplate?.name ?? '',
    when: scheduleMode === 'schedule' && scheduledAt ? formatDateTime(scheduledAt) : '',
  });
  const blockedReason = blocked?.reason;
  const blockedTarget = blocked?.pulseTarget;

  const mainAction = useMemo<FxMainActionSpec | null>(
    () =>
      canSend
        ? {
            id: 'broadcast-send',
            label,
            fullLabel,
            blocked: blockedReason ? { reason: blockedReason, pulseTarget: blockedTarget } : undefined,
            working: sending,
            onClick: () => {
              audienceAtSend.current = audienceCount;
              void sendOrSchedule();
            },
          }
        : null,
    [canSend, label, fullLabel, blockedReason, blockedTarget, sending, audienceCount, sendOrSchedule],
  );
  useRegisterMainAction(mainAction);

  const setSchedule = (mode: BroadcastFormValues['scheduleMode'], next: ScheduleParts) => {
    setValue('scheduleMode', mode, { shouldDirty: true });
    setValue('scheduledAt', mode === 'schedule' ? joinScheduledAt(next, timeZone) : null, { shouldDirty: true });
  };

  const saveDraft = async () => {
    if (!config || saving) return;
    setSaving(true);
    try {
      await config.onSave();
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    if (!config) return;
    if (isDirty) setDiscardOpen(true);
    else config.onCancel();
  };

  const [pendingNav, setPendingNav] = useState<(() => void) | null>(null);
  const guardNav = isDirty
    ? (proceed: () => void) => {
        setPendingNav(() => proceed);
        setDiscardOpen(true);
      }
    : undefined;

  const testReason = !channelId || !templateId ? 'Pick a channel and a template first.' : undefined;

  return (
    <Container width="fluid">
      <Form {...form}>
        <div className="flex flex-col gap-5">
          <PageHeader
            title="New broadcast"
            crumbs={[
              { label: 'Omnichannel', href: broadcastsListPath },
              { label: 'Broadcasts', href: broadcastsListPath },
              { label: 'New broadcast' },
            ]}
            description="Configure a WhatsApp broadcast campaign"
            guardNav={guardNav}
            actions={
              <>
                <FxIconAction
                  label="Save as draft"
                  icon="edit"
                  iconNode={<Save className="size-[18px]" aria-hidden="true" />}
                  disabledReason={saving ? 'Saving the draft.' : undefined}
                  onClick={() => void saveDraft()}
                />
                {canSend && (
                  <FxIconAction
                    label="Send a test message"
                    icon="send"
                    iconNode={<FlaskConical className="size-[18px]" aria-hidden="true" />}
                    disabledReason={testReason ?? (sending ? 'Sending the broadcast.' : undefined)}
                    onClick={() => setTestOpen(true)}
                  />
                )}
                <FxIconAction label="Discard changes" icon="discard" onClick={discard} />
              </>
            }
          />

          <div className="flex w-full max-w-[880px] flex-col gap-4">
            <DetailsSection
              name={name}
              labels={labels}
              editing
              onNameChange={(v) => setValue('name', v, { shouldDirty: true, shouldTouch: true })}
              onLabelsChange={(v) => setValue('labels', v, { shouldDirty: true })}
              error={formState.errors.name?.message}
              pulseTarget={BC_PULSE.name}
            />

            <AudienceSection
              workspaceId={workspaceId}
              editing
              value={audience}
              onChange={(next) => setValue('audience', next, { shouldDirty: true })}
              pulseTarget={BC_PULSE.audience}
            />

            <ChannelSection
              channels={channels}
              value={channelId}
              editing
              onChange={(next) => {
                setValue('channelId', next, { shouldDirty: true });
                // Changing the channel clears the template and its bindings (AC-BRD-06).
                setValue('templateId', '', { shouldDirty: true });
                setValue('bindings', { header: [], body: [], buttons: [] }, { shouldDirty: true });
              }}
              error={formState.errors.channelId?.message}
              pulseTarget={BC_PULSE.channel}
            />

            <section className="flex flex-col gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-5">
              <h2 className="text-base font-bold text-(--fx-ink)">Message</h2>
              <MessageSectionHeader
                templates={templates}
                templateId={templateId}
                editing
                pulseTarget={BC_PULSE.template}
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
                <div data-fx-pulse-target={BC_PULSE.bindings}>
                  <BindingEditor
                    channelId={channelId}
                    template={selectedTemplate}
                    editing
                    header={bindings.header}
                    body={bindings.body}
                    buttons={bindings.buttons}
                    onChangeHeader={(next) => setValue('bindings.header', next, { shouldDirty: true })}
                    onChangeBody={(next) => setValue('bindings.body', next, { shouldDirty: true })}
                    onChangeButtons={(next) => setValue('bindings.buttons', next, { shouldDirty: true })}
                    headerErrors={bindingSlotErrors(formState.errors, 'header', bindings.header.length)}
                    bodyErrors={bindingSlotErrors(formState.errors, 'body', bindings.body.length)}
                    buttonsErrors={bindingSlotErrors(formState.errors, 'buttons', bindings.buttons.length)}
                  />
                </div>
              )}
            </section>

            <FxScheduleSection
              scheduleMode={scheduleMode}
              parts={parts}
              timeZone={timeZone}
              onMode={(mode) => setSchedule(mode, parts)}
              onParts={(next) => {
                setParts(next);
                setSchedule('schedule', next);
              }}
            />

            <ReviewSummary
              values={values}
              channelName={selectedChannel?.name ?? ''}
              templateName={selectedTemplate?.name ?? ''}
              audienceCount={audienceCount}
            />
          </div>
        </div>

        {canSend && (
          <TestSendDialog
            open={testOpen}
            onOpenChange={setTestOpen}
            workspaceId={workspaceId}
            ensureBroadcastId={ensureDraftId}
          />
        )}
        <FxDiscardDialog
          open={discardOpen}
          name={name.trim() || undefined}
          onKeep={() => {
            setDiscardOpen(false);
            setPendingNav(null);
          }}
          onDiscard={() => {
            setDiscardOpen(false);
            const proceed = pendingNav;
            setPendingNav(null);
            if (proceed) proceed();
            else config?.onCancel();
          }}
        />
      </Form>
    </Container>
  );
}
