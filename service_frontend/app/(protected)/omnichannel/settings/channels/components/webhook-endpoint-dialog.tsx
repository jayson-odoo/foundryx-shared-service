'use client';

import { useEffect, useState } from 'react';
import { Loader2, Webhook } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/platform/multi-select';
import type { WebhookEndpoint, WebhookEventType } from '@/types/whatsapp-webhook';
import { WEBHOOK_EVENT_OPTIONS } from './webhook-status';
import { useWebhooks } from './use-webhooks';
import { WebhookSecretPanel } from './webhook-secret-panel';

export interface WebhookEndpointDialogProps {
  channelId: string;
  /** When set the dialog edits this endpoint; otherwise it creates a new one. */
  endpoint: WebhookEndpoint | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful create/edit so the list can refresh. */
  onSaved: () => void;
}

function isHttpsUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Create / edit a consumer-webhook endpoint. On CREATE the signing secret is
 * revealed ONCE after submit (the only time it exists client-side); EDIT saves
 * and closes. Name / URL (https) / ≥1 event are validated inline.
 */
export function WebhookEndpointDialog({
  channelId,
  endpoint,
  open,
  onOpenChange,
  onSaved,
}: WebhookEndpointDialogProps) {
  const { saving, create, update } = useWebhooks(channelId);
  const editing = endpoint !== null;

  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [events, setEvents] = useState<WebhookEventType[]>([]);
  const [attempted, setAttempted] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);

  // Seed / clear form state whenever the dialog opens or the target changes.
  useEffect(() => {
    if (open) {
      setName(endpoint?.name ?? '');
      setUrl(endpoint?.url ?? '');
      setEvents(endpoint?.events ?? []);
      setAttempted(false);
      setSecret(null);
    }
  }, [open, endpoint]);

  const trimmedName = name.trim();
  const trimmedUrl = url.trim();
  const nameError = attempted && !trimmedName ? 'Enter a name.' : null;
  const urlError =
    attempted && !isHttpsUrl(trimmedUrl) ? 'Enter a valid https:// URL.' : null;
  const eventsError = attempted && events.length === 0 ? 'Select at least one event.' : null;
  const valid = Boolean(trimmedName) && isHttpsUrl(trimmedUrl) && events.length > 0;

  const submit = async () => {
    setAttempted(true);
    if (!valid) return;
    try {
      if (editing && endpoint) {
        await update(endpoint.id, { name: trimmedName, url: trimmedUrl, events });
        toast.success('Endpoint updated.');
        onSaved();
        onOpenChange(false);
      } else {
        const result = await create({ name: trimmedName, url: trimmedUrl, events });
        setSecret(result.signingSecret);
        onSaved();
      }
    } catch {
      toast.error('Could not save the endpoint. Please retry.');
    }
  };

  const revealed = secret !== null;
  const title = revealed
    ? 'Endpoint created'
    : editing
      ? 'Edit endpoint'
      : 'Add endpoint';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {revealed && secret ? (
          <>
            <DialogBody>
              <WebhookSecretPanel secret={secret} />
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogBody className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="webhook-name">Name</Label>
                <Input
                  id="webhook-name"
                  autoFocus
                  placeholder="e.g. CRM sync"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
                {nameError && <p className="text-xs text-destructive">{nameError}</p>}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="webhook-url">Endpoint URL</Label>
                <Input
                  id="webhook-url"
                  placeholder="https://hooks.example.com/whatsapp"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                {urlError && <p className="text-xs text-destructive">{urlError}</p>}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>Events</Label>
                <MultiSelect
                  options={WEBHOOK_EVENT_OPTIONS}
                  value={events}
                  onChange={(v) => setEvents(v as WebhookEventType[])}
                  placeholder="Select events…"
                  searchPlaceholder="Search events…"
                />
                {eventsError && <p className="text-xs text-destructive">{eventsError}</p>}
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submit} disabled={saving}>
                {saving ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Webhook className="size-4" />
                )}
                {editing ? 'Save changes' : 'Add endpoint'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
