'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { useCan } from '@/hooks/use-can';
import { useMeetingsSettings } from '@/hooks/use-meetings-settings';
import {
  useMeetingsConnections,
  type MeetingsProviderKey,
} from '@/hooks/use-meetings-connections';
import type { ConnectionStatus } from '@/types/integration';

const MINUTES_LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'ms', label: 'Malay' },
  { value: 'zh', label: 'Chinese' },
  { value: 'ta', label: 'Tamil' },
  { value: 'id', label: 'Indonesian' },
  { value: 'th', label: 'Thai' },
  { value: 'vi', label: 'Vietnamese' },
];

// Explicit choices only — "Keep" is an option, never a magic number to type.
const RETENTION_OPTIONS = [
  { value: '30', label: '30 days' },
  { value: '60', label: '60 days' },
  { value: '90', label: '90 days' },
  { value: '180', label: '180 days' },
  { value: '365', label: '365 days' },
  { value: '0', label: 'Keep' },
];

const CONNECTION_CARDS: { provider: MeetingsProviderKey; title: string }[] = [
  { provider: 'google_dwd', title: 'Google Calendar' },
  { provider: 'meet_bot', title: 'Notetaker account' },
];

// The one card that also carries a value the operator has to hand out.
const SERVICE_ACCOUNT_CARD: MeetingsProviderKey = 'google_dwd';

const STATUS_TONE: Record<ConnectionStatus, 'success' | 'warning' | 'destructive'> = {
  ACTIVE: 'success',
  UNVERIFIED: 'warning',
  ERROR: 'destructive',
};

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  ACTIVE: 'Connected',
  UNVERIFIED: 'Not tested',
  ERROR: 'Error',
};

/**
 * Settings → Meetings (S0 plan §4, AC-S0-4/5/14).
 *
 * Connections are NOT re-implemented here: each card links into the shared
 * `/settings/integrations` form with the provider already chosen, so the field
 * schema, the encrypted write-only credentials and the Test button all come from
 * the provider registry (reuse mandate).
 */
export function MeetingsSettingsView() {
  const { can } = useCan();
  const canManage = can('meetings.settings.manage');
  const { settings, loading, saving, save } = useMeetingsSettings();
  const { byProvider, loading: connectionsLoading } = useMeetingsConnections();
  const serviceAccountEmail = settings?.calendarServiceAccountEmail ?? null;

  const [minutesLanguage, setMinutesLanguage] = useState('en');
  const [audioRetentionDays, setAudioRetentionDays] = useState('90');
  const [botDisplayName, setBotDisplayName] = useState('');
  const [consentMessage, setConsentMessage] = useState('');

  useEffect(() => {
    if (!settings) return;
    setMinutesLanguage(settings.minutesLanguage);
    setAudioRetentionDays(String(settings.audioRetentionDays));
    setBotDisplayName(settings.botDisplayName ?? '');
    setConsentMessage(settings.consentMessage ?? '');
  }, [settings]);

  const onSave = async () => {
    try {
      await save({
        minutesLanguage,
        audioRetentionDays: Number(audioRetentionDays),
        botDisplayName: botDisplayName.trim() || null,
        consentMessage: consentMessage.trim() || null,
      });
      toast.success('Settings saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Connections</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {CONNECTION_CARDS.map(({ provider, title }) => {
            const connection = byProvider[provider];
            return (
              <div
                key={provider}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-4"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm font-medium">{title}</span>
                  {connection && (
                    <Badge
                      variant={STATUS_TONE[connection.status]}
                      appearance="light"
                      size="sm"
                    >
                      {STATUS_LABEL[connection.status]}
                    </Badge>
                  )}
                  {/* The address users share their calendar WITH. It comes off
                      the stored key's client_email; the key itself never
                      leaves the server. */}
                  {provider === SERVICE_ACCOUNT_CARD && serviceAccountEmail && (
                    <span className="max-w-[16rem] text-sm text-muted-foreground">
                      <ClampedText text={serviceAccountEmail} lines={1} />
                    </span>
                  )}
                </div>
                <Button variant="outline" size="sm" disabled={connectionsLoading} asChild>
                  <Link
                    href={
                      connection
                        ? `/settings/integrations/${connection.id}`
                        : `/settings/integrations/new?provider=${provider}`
                    }
                  >
                    {connection ? 'Open' : 'Connect'}
                  </Link>
                </Button>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Meetings</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <div className="flex max-w-xs flex-col gap-1.5">
            <Label>Minutes language</Label>
            <SearchSelect
              ariaLabel="Minutes language"
              value={minutesLanguage}
              onChange={(v) => setMinutesLanguage(v || 'en')}
              options={MINUTES_LANGUAGES}
              disabled={!canManage || loading}
            />
          </div>

          <div className="flex max-w-xs flex-col gap-1.5">
            <Label>Recordings</Label>
            <SearchSelect
              ariaLabel="Recordings"
              value={audioRetentionDays}
              onChange={(v) => setAudioRetentionDays(v || '90')}
              options={RETENTION_OPTIONS}
              disabled={!canManage || loading}
            />
          </div>

          <div className="flex max-w-md flex-col gap-1.5">
            <Label htmlFor="meetings-bot-name">Notetaker display name</Label>
            <Input
              id="meetings-bot-name"
              value={botDisplayName}
              placeholder="Notetaker"
              disabled={!canManage || loading}
              onChange={(e) => setBotDisplayName(e.target.value)}
            />
          </div>

          <div className="flex max-w-2xl flex-col gap-1.5">
            <Label htmlFor="meetings-consent">Consent message</Label>
            <Textarea
              id="meetings-consent"
              rows={3}
              value={consentMessage}
              placeholder="This meeting is being recorded and summarised."
              disabled={!canManage || loading}
              onChange={(e) => setConsentMessage(e.target.value)}
            />
          </div>

          {canManage && (
            <div>
              <Button disabled={saving || loading} onClick={() => void onSave()}>
                Save
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
