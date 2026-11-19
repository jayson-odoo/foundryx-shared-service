'use client';

/**
 * Settings > Meetings with the Foundryx UIUX switch on (slice W4-SETTINGS).
 * The same connections, bot runs and settings, and the same save request as
 * with the switch off; what changes is how it reads:
 * - "Save meeting settings" is the page's red action (today's button, in the
 *   page header); a user who may not change the settings sees them as plain
 *   text and no red action.
 * - The connection cards keep Connect / Open on each card, as today.
 * - The bot runs list declares its status column and phone card lines.
 * - Saving ends with a done toast whose Undo writes the earlier settings back
 *   (the same endpoint, the same fields with the earlier values).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { toast } from '@/lib/toast';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { ResourceList } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxField, FxNoteField } from '@/components/fx/fields';
import { CONNECTION_STATUS_REGISTRY } from '../integrations/components/connection-status';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { useMeetingsBotRuns } from '@/hooks/use-meetings-bot-runs';
import { useMeetingsSettings } from '@/hooks/use-meetings-settings';
import { useMeetingsConnections } from '@/hooks/use-meetings-connections';
import type { MeetingsSettings, MeetingsSettingsInput } from '@/types/meetings';
import { FxPlainSetting, useFxUserName } from '../general/fx-settings-bits';
import { useBotRunsListConfig } from './use-bot-runs-list-config';
import {
  CONNECTION_CARDS,
  MINUTES_LANGUAGES,
  RETENTION_OPTIONS,
  SERVICE_ACCOUNT_CARD,
} from './meetings-settings-view';

interface FormValues {
  minutesLanguage: string;
  audioRetentionDays: string;
  botDisplayName: string;
  consentMessage: string;
}

/** The save body for the typed values, exactly as the switch-off page builds it. */
export function fxMeetingsBody(values: FormValues): MeetingsSettingsInput {
  return {
    minutesLanguage: values.minutesLanguage,
    audioRetentionDays: Number(values.audioRetentionDays),
    botDisplayName: values.botDisplayName.trim() || null,
    consentMessage: values.consentMessage.trim() || null,
  };
}

/** The body that puts stored settings back as they were. */
function bodyOf(s: MeetingsSettings): MeetingsSettingsInput {
  return {
    minutesLanguage: s.minutesLanguage,
    audioRetentionDays: s.audioRetentionDays,
    botDisplayName: s.botDisplayName,
    consentMessage: s.consentMessage,
  };
}

const labelOf = (options: { value: string; label: string }[], value: string) =>
  options.find((o) => o.value === value)?.label ?? value;

export function FxMeetingsSettingsView() {
  const { can } = useCan();
  const canManage = can('meetings.settings.manage');
  const byWhom = useFxUserName();
  const { settings, loading, saving, save } = useMeetingsSettings();
  const { byProvider, loading: connectionsLoading } = useMeetingsConnections();
  const serviceAccountEmail = settings?.calendarServiceAccountEmail ?? null;
  const { runs, error: runsError } = useMeetingsBotRuns(7);
  const { timeZone, formatDateTime } = useDatetime();
  const baseRunsConfig = useBotRunsListConfig(runs, { timeZone });
  const botRunsConfig = useMemo(
    () => ({
      ...baseRunsConfig,
      fx: {
        noun: 'bot runs',
        compactStates: true,
        columnKind: { reason: 'status' as const },
        cardLines: [['meeting'], ['started', 'duration']],
        phoneHidden: ['ended'],
      },
    }),
    [baseRunsConfig],
  );

  const [values, setValues] = useState<FormValues>({
    minutesLanguage: 'en',
    audioRetentionDays: '90',
    botDisplayName: '',
    consentMessage: '',
  });

  useEffect(() => {
    if (!settings) return;
    setValues({
      minutesLanguage: settings.minutesLanguage,
      audioRetentionDays: String(settings.audioRetentionDays),
      botDisplayName: settings.botDisplayName ?? '',
      consentMessage: settings.consentMessage ?? '',
    });
  }, [settings]);

  const set = (key: keyof FormValues, value: string) => setValues((v) => ({ ...v, [key]: value }));

  const onSave = async () => {
    const before = settings;
    try {
      await save(fxMeetingsBody(values));
      toast.fxDone({
        what: 'Meeting settings saved',
        byWhom,
        undo: before
          ? () =>
              void save(bodyOf(before)).catch(() =>
                toast.error("Couldn't undo. The new settings stay."),
              )
          : undefined,
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    }
  };

  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const ready = canManage && !loading;
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      ready
        ? {
            id: 'save-meeting-settings',
            label: 'Save meeting settings',
            onClick: () => void onSaveRef.current(),
            working: saving,
          }
        : null,
    [ready, saving],
  );
  useRegisterMainAction(main);

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
                className="flex flex-wrap items-center justify-between gap-3 rounded-(--fx-r-l) border border-(--fx-line) p-4"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-3">
                  <span className="text-sm font-medium">{title}</span>
                  {connection && (
                    <StatusBadge
                      status={connection.status}
                      registry={CONNECTION_STATUS_REGISTRY}
                      size="sm"
                    />
                  )}
                  {provider === SERVICE_ACCOUNT_CARD && serviceAccountEmail && (
                    <span className="max-w-[16rem] min-w-0 text-sm text-(--fx-ink-2)">
                      <ClampedText text={serviceAccountEmail} lines={1} />
                    </span>
                  )}
                  {provider === 'meet_bot' && connection?.lastTestedAt && (
                    <span className="text-sm text-(--fx-ink-2)">
                      {formatDateTime(connection.lastTestedAt)}
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
                    {connection ? `Open ${title}` : `Connect ${title}`}
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
            <CardTitle>Bot runs</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent>
          {runsError ? (
            <p className="py-5 text-sm text-(--fx-act)">{runsError}</p>
          ) : (
            <ResourceList config={botRunsConfig} hideHeader />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Meetings</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {canManage ? (
            <>
              <FxField label="Minutes language" className="max-w-xs">
                <SearchSelect
                  ariaLabel="Minutes language"
                  value={values.minutesLanguage}
                  onChange={(v) => set('minutesLanguage', v || 'en')}
                  options={MINUTES_LANGUAGES}
                  disabled={loading}
                />
              </FxField>
              <FxField label="Recordings" className="max-w-xs">
                <SearchSelect
                  ariaLabel="Recordings"
                  value={values.audioRetentionDays}
                  onChange={(v) => set('audioRetentionDays', v || '90')}
                  options={RETENTION_OPTIONS}
                  disabled={loading}
                />
              </FxField>
              <FxField label="Notetaker display name" id="meetings-bot-name" className="max-w-md">
                <Input
                  id="meetings-bot-name"
                  value={values.botDisplayName}
                  placeholder="Notetaker"
                  disabled={loading}
                  onChange={(e) => set('botDisplayName', e.target.value)}
                />
              </FxField>
              <FxField label="Consent message" id="meetings-consent" className="max-w-2xl">
                <FxNoteField
                  id="meetings-consent"
                  value={values.consentMessage}
                  placeholder="This meeting is being recorded and summarised."
                  disabled={loading}
                  onChange={(e) => set('consentMessage', e.target.value)}
                />
              </FxField>
            </>
          ) : (
            <>
              <FxPlainSetting label="Minutes language">
                {labelOf(MINUTES_LANGUAGES, values.minutesLanguage)}
              </FxPlainSetting>
              <FxPlainSetting label="Recordings">
                {labelOf(RETENTION_OPTIONS, values.audioRetentionDays)}
              </FxPlainSetting>
              <FxPlainSetting label="Notetaker display name">
                {values.botDisplayName || 'Notetaker'}
              </FxPlainSetting>
              <FxPlainSetting label="Consent message">
                {values.consentMessage || '-'}
              </FxPlainSetting>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
