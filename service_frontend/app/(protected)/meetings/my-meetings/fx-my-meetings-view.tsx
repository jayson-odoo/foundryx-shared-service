'use client';

/**
 * My meetings with the Foundryx UIUX switch on (slice W4-ACCOUNT). The same
 * three writes as with the switch off, with the same values: the master
 * "Record my meetings" switch, the Calendar address (saved when the field is
 * left) and a meeting's Capture switch. What changes is how it reads:
 * - with recording off, "Record my meetings" is the page's red action and
 *   the empty list says so in one line (the switch above does the same);
 * - every write ends with a done toast whose Undo sends the earlier value
 *   back through the same request;
 * - a Calendar address that is not an email shows its message under the
 *   field and is not sent (as today), keeping what was typed;
 * - "Shared with" is Hold to Copy;
 * - the list shows 12-hour times, puts the status on a phone card's top line
 *   and the capture switch at the end of its last line.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { ResourceList } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { FxHoldToCopy } from '@/components/fx/copy/hold-to-copy';
import { FX_FIELD_LABEL, FxField } from '@/components/fx/fields';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { useMyMeetings } from '@/hooks/use-my-meetings';
import { useDatetime } from '@/hooks/use-datetime';
import type { MeetingsEvent } from '@/types/meetings';
import { useUpcomingEventsListConfig } from './use-upcoming-events-list-config';

/** The same check as the switch-off page. */
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const failed = (e: unknown) =>
  toast.error(e instanceof Error ? e.message : 'Could not save the change.');

export function FxMyMeetingsView() {
  const { optIn, events, loading, saving, error, setEnabled, setCalendarEmail, setEventOptOut } =
    useMyMeetings();
  const { timeZone } = useDatetime();

  const enabled = optIn?.enabled ?? false;
  const storedCalendar = optIn?.calendarEmail ?? '';
  const [calendarDraft, setCalendarDraft] = useState('');
  const [calendarWhy, setCalendarWhy] = useState<string | null>(null);

  useEffect(() => {
    setCalendarDraft(optIn?.calendarEmail ?? '');
  }, [optIn?.calendarEmail]);

  const toggleMaster = useCallback(
    async (next: boolean, withUndo = true) => {
      try {
        await setEnabled(next);
      } catch (e) {
        failed(e);
        return;
      }
      toast.fxDone({
        what: next ? 'Recording turned on for your meetings' : 'Recording turned off for your meetings',
        undo: withUndo ? () => void toggleMaster(!next, false) : undefined,
      });
    },
    [setEnabled],
  );

  const saveCalendar = useCallback(
    async (next: string | null, previous: string | null, withUndo: boolean) => {
      try {
        await setCalendarEmail(next);
      } catch (e) {
        failed(e);
        setCalendarDraft(previous ?? '');
        return;
      }
      toast.fxDone({
        what: next ? `Calendar set to ${next}` : 'Calendar set back to your sign-in email',
        undo: withUndo ? () => void saveCalendar(previous, next, false) : undefined,
      });
    },
    [setCalendarEmail],
  );

  const commitCalendar = useCallback(() => {
    const next = calendarDraft.trim();
    if (next === storedCalendar) return;
    if (next && !EMAIL_RE.test(next)) {
      setCalendarWhy('Enter a valid email address.');
      return;
    }
    void saveCalendar(next || null, storedCalendar || null, true);
  }, [calendarDraft, saveCalendar, storedCalendar]);

  const toggleCapture = useCallback(
    (event: MeetingsEvent, capture: boolean, withUndo = true) => {
      void setEventOptOut(event.id, !capture).then(
        () =>
          toast.fxDone({
            what: `${capture ? 'Capture turned on' : 'Capture turned off'} for ${event.title ?? 'this meeting'}`,
            undo: withUndo ? () => toggleCapture(event, !capture, false) : undefined,
          }),
        failed,
      );
    },
    [setEventOptOut],
  );

  const config = useUpcomingEventsListConfig(events, {
    timeZone,
    saving,
    onToggleCapture: toggleCapture,
    fx: true,
  });

  // With recording off, turning it on is what this page is for.
  const toggleRef = useRef(toggleMaster);
  toggleRef.current = toggleMaster;
  const showMain = Boolean(optIn) && !enabled;
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      showMain
        ? {
            id: 'record-my-meetings',
            label: 'Record my meetings',
            onClick: () => void toggleRef.current(true),
            working: saving,
            blocked: loading ? { reason: 'Still loading.' } : undefined,
          }
        : null,
    [showMain, saving, loading],
  );
  useRegisterMainAction(main);

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardContent className="flex flex-col gap-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <label htmlFor="meetings-master-toggle" className={FX_FIELD_LABEL}>
              Record my meetings
            </label>
            <Switch
              id="meetings-master-toggle"
              aria-label="Record my meetings"
              checked={enabled}
              disabled={loading || saving}
              onCheckedChange={(next) => void toggleMaster(next)}
            />
          </div>

          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5">
            <label htmlFor="meetings-calendar-email" className={`${FX_FIELD_LABEL} pt-2`}>
              Calendar
            </label>
            <FxField tone="error" message={calendarWhy} className="w-full max-w-xs">
              <Input
                id="meetings-calendar-email"
                type="email"
                value={calendarDraft}
                placeholder={optIn?.serviceAccountEmail ? 'me@gmail.com' : undefined}
                disabled={loading || saving}
                aria-invalid={calendarWhy ? true : undefined}
                onChange={(e) => {
                  setCalendarWhy(null);
                  setCalendarDraft(e.target.value);
                }}
                onBlur={commitCalendar}
              />
            </FxField>
          </div>

          {optIn?.serviceAccountEmail && (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <span className={FX_FIELD_LABEL}>Shared with</span>
              <span className="max-w-xs min-w-0 text-sm text-(--fx-ink-2)">
                <FxHoldToCopy text={optIn.serviceAccountEmail}>
                  <ClampedText text={optIn.serviceAccountEmail} lines={1} />
                </FxHoldToCopy>
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {error && <p className="text-sm font-semibold text-(--fx-act)">{error}</p>}

      {enabled ? (
        <ResourceList config={config} hideHeader />
      ) : (
        <Card>
          <CardContent className="py-14 text-center text-sm text-(--fx-ink-2)">
            No meetings while recording is off.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
