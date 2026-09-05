'use client';

/**
 * Builder sections (plan 29, AC-BRD-04) - Details / Channel / Message /
 * Schedule / Review, rendered as grouped Cards (the `channel-form-fields.tsx`
 * pattern) stacked in ONE tab. `AudienceSection` and `BindingEditor` live in
 * their own files (reused pieces); everything else is local to this file.
 */
import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { useDatetime } from '@/hooks/use-datetime';
import { channelService } from '@/services/channel-service';
import { conversationService } from '@/services/conversation-service';
import { broadcastService } from '@/services/broadcast-service';
import { zonedTimeToUtc, utcToZonedInputValue } from '@/lib/datetime';
import type { Channel, ConversationThread, WhatsAppTemplate } from '@/types/omnichannel';
import { BROADCAST_STATUS_REGISTRY } from './broadcast-status';
import type { BroadcastFormValues } from './broadcast-schema';

// ---------------------------------------------------------------------------
// Details
// ---------------------------------------------------------------------------

export function DetailsSection({
  name,
  labels,
  editing,
  onNameChange,
  onLabelsChange,
  error,
}: {
  name: string;
  labels: string[];
  editing: boolean;
  onNameChange: (v: string) => void;
  onLabelsChange: (v: string[]) => void;
  error?: string;
}) {
  const [draft, setDraft] = useState('');

  const addLabel = () => {
    const v = draft.trim();
    if (!v || labels.includes(v)) {
      setDraft('');
      return;
    }
    onLabelsChange([...labels, v]);
    setDraft('');
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Details</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">Name *</label>
          <Input value={name} onChange={(e) => onNameChange(e.target.value)} disabled={!editing} />
          {error && <ClampedText text={error} lines={2} className="text-xs text-destructive" />}
        </div>
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">Labels</label>
          <div className="flex flex-wrap items-center gap-1.5">
            {labels.map((l) => (
              <Badge key={l} size="sm" variant="secondary" appearance="light" className="gap-1">
                {l}
                {editing && (
                  <button
                    type="button"
                    className={cn(PRESSED_CLASS, 'inline-flex')}
                    onClick={() => onLabelsChange(labels.filter((x) => x !== l))}
                    aria-label={`Remove label ${l}`}
                  >
                    <X className="size-3" />
                  </button>
                )}
              </Badge>
            ))}
            {editing && (
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addLabel();
                  }
                }}
                onBlur={addLabel}
                className="h-8 w-32"
              />
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Channel
// ---------------------------------------------------------------------------

/** Active, non-trashed channels of the workspace (AC-BRD-06) - lifted to a
 *  hook so both `ChannelSection` and the Review summary can resolve a name
 *  from the selected channel id without fetching twice. */
export function useActiveChannels(workspaceId: string | null): Channel[] {
  const [channels, setChannels] = useState<Channel[]>([]);
  useEffect(() => {
    if (!workspaceId) {
      setChannels([]);
      return;
    }
    channelService
      .listByWorkspace(workspaceId)
      .then((rows) => setChannels(rows.filter((c) => c.isActive && !c.isTrashed)))
      .catch(() => setChannels([]));
  }, [workspaceId]);
  return channels;
}

export function ChannelSection({
  channels,
  value,
  editing,
  onChange,
  error,
}: {
  channels: Channel[];
  value: string;
  editing: boolean;
  onChange: (channelId: string) => void;
  error?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Channel</CardTitle>
      </CardHeader>
      <CardContent className="py-4">
        <div className="max-w-sm space-y-1.5">
          <label className="text-sm text-muted-foreground">Channel *</label>
          <SearchSelect
            options={channels.map((c) => ({ label: c.name, value: c.id }))}
            value={value || null}
            onChange={onChange}
            disabled={!editing}
            ariaLabel="Channel"
            className="w-full"
          />
          {error && <ClampedText text={error} lines={2} className="text-xs text-destructive" />}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Message
// ---------------------------------------------------------------------------

export function useApprovedTemplates(channelId: string): WhatsAppTemplate[] {
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  useEffect(() => {
    if (!channelId) {
      setTemplates([]);
      return;
    }
    conversationService
      .listTemplates(channelId)
      .then((rows) => setTemplates(rows.filter((t) => t.status === 'APPROVED' && (!t.headerFormat || t.headerFormat === 'TEXT'))))
      .catch(() => setTemplates([]));
  }, [channelId]);
  return templates;
}

export function MessageSectionHeader({
  templates,
  templateId,
  editing,
  onChange,
  error,
}: {
  templates: WhatsAppTemplate[];
  templateId: string;
  editing: boolean;
  onChange: (templateId: string) => void;
  error?: string;
}) {
  return (
    <div className="max-w-sm space-y-1.5">
      <label className="text-sm text-muted-foreground">Template *</label>
      <SearchSelect
        options={templates.map((t) => ({ label: `${t.name} (${t.language ?? 'default'})`, value: t.id }))}
        value={templateId || null}
        onChange={onChange}
        disabled={!editing}
        ariaLabel="Template"
        className="w-full"
      />
      {error && <ClampedText text={error} lines={2} className="text-xs text-destructive" />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Schedule
// ---------------------------------------------------------------------------

export function ScheduleSection({
  scheduleMode,
  scheduledAt,
  editing,
  onChange,
  error,
}: {
  scheduleMode: BroadcastFormValues['scheduleMode'];
  scheduledAt: string | null;
  editing: boolean;
  onChange: (mode: BroadcastFormValues['scheduleMode'], scheduledAt: string | null) => void;
  error?: string;
}) {
  const { timeZone } = useDatetime();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Schedule</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 py-4">
        <ToggleGroup
          type="single"
          value={scheduleMode}
          onValueChange={(v) => {
            if (!v) return;
            if (v === 'now') onChange('now', null);
            else onChange('schedule', scheduledAt);
          }}
          disabled={!editing}
        >
          <ToggleGroupItem value="now">Send now</ToggleGroupItem>
          <ToggleGroupItem value="schedule">Schedule for</ToggleGroupItem>
        </ToggleGroup>
        {scheduleMode === 'schedule' && (
          <div className="max-w-xs space-y-1.5">
            <Input
              type="datetime-local"
              aria-label="Scheduled for"
              value={utcToZonedInputValue(scheduledAt, timeZone)}
              disabled={!editing}
              onChange={(e) => {
                if (!e.target.value) {
                  onChange('schedule', null);
                  return;
                }
                const utc = zonedTimeToUtc(e.target.value, timeZone);
                onChange('schedule', utc ? utc.toISOString() : null);
              }}
            />
            <ClampedText text={`Timezone: ${timeZone}`} lines={1} className="text-xs text-muted-foreground" />
          </div>
        )}
        {error && <ClampedText text={error} lines={2} className="text-xs text-destructive" />}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------

export function ReviewSummary({
  values,
  channelName,
  templateName,
  audienceCount,
}: {
  values: BroadcastFormValues;
  channelName: string;
  templateName: string;
  audienceCount: number | null;
}) {
  const { formatDateTime } = useDatetime();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Review</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 py-4 text-sm">
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Audience</span>
          <span>{audienceCount ?? '-'} recipient(s)</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Channel</span>
          <ClampedText text={channelName || '-'} lines={1} className="text-end" />
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Template</span>
          <ClampedText text={templateName || '-'} lines={1} className="text-end" />
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Schedule</span>
          <span>{values.scheduleMode === 'now' ? 'Send now' : values.scheduledAt ? formatDateTime(values.scheduledAt) : '-'}</span>
        </div>
      </CardContent>
    </Card>
  );
}

export function DetailStatusChip({ status }: { status: keyof typeof BROADCAST_STATUS_REGISTRY }) {
  return <StatusBadge status={status} registry={BROADCAST_STATUS_REGISTRY} />;
}

/** Test-send dialog (AC-BRD-09) - pick ONE contact, send through the same
 *  broadcast (creates no recipient row, D-A4-18). `ensureBroadcastId`
 *  auto-saves the in-progress draft the first time so a not-yet-persisted
 *  broadcast can still be test-sent. */
export function TestSendDialog({
  open,
  onOpenChange,
  workspaceId,
  ensureBroadcastId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string | null;
  ensureBroadcastId: () => Promise<string | null>;
}) {
  const [contacts, setContacts] = useState<ConversationThread[]>([]);
  const [contactId, setContactId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!open || !workspaceId) return;
    conversationService
      .listThreads({ workspaceId })
      .then(setContacts)
      .catch(() => setContacts([]));
  }, [open, workspaceId]);

  const submit = async () => {
    if (!workspaceId || !contactId) return;
    setSending(true);
    try {
      const id = await ensureBroadcastId();
      if (!id) return;
      await broadcastService.testSend(workspaceId, id, contactId);
      toast.success('Test message sent.');
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Could not send the test message.');
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Send test message</DialogTitle>
          <DialogDescription>One message, sent through this broadcast&apos;s template and bindings.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-sm text-muted-foreground">Contact</label>
            <SearchSelect
              options={contacts.map((c) => ({ label: `${c.name} (${c.phone ?? 'no phone'})`, value: c.id }))}
              value={contactId}
              onChange={setContactId}
              ariaLabel="Test-send contact"
              className="w-full"
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button onClick={submit} disabled={!contactId || sending}>
            Send test
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function PrimaryActionsRow({
  scheduleMode,
  canSubmit,
  sending,
  onTestSend,
  onSubmit,
  testDisabled,
}: {
  scheduleMode: BroadcastFormValues['scheduleMode'];
  canSubmit: boolean;
  sending: boolean;
  testDisabled: boolean;
  onTestSend: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" variant="outline" onClick={onTestSend} disabled={testDisabled || sending}>
        Send test message
      </Button>
      <Button type="button" onClick={onSubmit} disabled={!canSubmit || sending}>
        {scheduleMode === 'now' ? 'Send now' : 'Schedule broadcast'}
      </Button>
    </div>
  );
}
