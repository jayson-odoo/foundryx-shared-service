'use client';

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { ResourceList } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { useMyMeetings } from '@/hooks/use-my-meetings';
import { useDatetime } from '@/hooks/use-datetime';
import type { MeetingsEvent } from '@/types/meetings';
import { useUpcomingEventsListConfig } from './use-upcoming-events-list-config';

/**
 * My meetings (S0 plan §4, AC-S0-6..9).
 *
 * One master toggle and, once it is on, the caller's upcoming events with a
 * capture switch per row. With the toggle off there is nothing to list - the
 * toggle itself is the next-step CTA (AC-S0-9), which is why the empty state
 * carries a control and no explanation.
 *
 * The Calendar field is the second control, and it exists because the login
 * email is not always the calendar a user can share: a Workspace that blocks
 * external sharing forces them to share a personal calendar instead. Blank means
 * their login email. The service-account address sits beside it as a VALUE to
 * copy, not as a sentence of instructions.
 */
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function MyMeetingsView() {
  const { optIn, events, loading, saving, error, setEnabled, setCalendarEmail, setEventOptOut } =
    useMyMeetings();
  const { timeZone } = useDatetime();

  const enabled = optIn?.enabled ?? false;
  const storedCalendar = optIn?.calendarEmail ?? '';
  const [calendarDraft, setCalendarDraft] = useState('');

  useEffect(() => {
    setCalendarDraft(optIn?.calendarEmail ?? '');
  }, [optIn?.calendarEmail]);

  const commitCalendar = useCallback(async () => {
    const next = calendarDraft.trim();
    if (next === storedCalendar) return;
    if (next && !EMAIL_RE.test(next)) {
      toast.error('Enter a valid email address.');
      setCalendarDraft(storedCalendar);
      return;
    }
    try {
      await setCalendarEmail(next || null);
      toast.success('Saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the change.');
      setCalendarDraft(storedCalendar);
    }
  }, [calendarDraft, setCalendarEmail, storedCalendar]);

  const toggleMaster = useCallback(
    async (next: boolean) => {
      try {
        await setEnabled(next);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Could not save the change.');
      }
    },
    [setEnabled],
  );

  const toggleCapture = useCallback(
    (event: MeetingsEvent, capture: boolean) => {
      void setEventOptOut(event.id, !capture).catch((e) => {
        toast.error(e instanceof Error ? e.message : 'Could not save the change.');
      });
    },
    [setEventOptOut],
  );

  const config = useUpcomingEventsListConfig(events, {
    timeZone,
    saving,
    onToggleCapture: toggleCapture,
  });

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardContent className="flex flex-col gap-5 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Label htmlFor="meetings-master-toggle" className="text-sm font-medium">
              Record my meetings
            </Label>
            <Switch
              id="meetings-master-toggle"
              aria-label="Record my meetings"
              checked={enabled}
              disabled={loading || saving}
              onCheckedChange={(next) => void toggleMaster(next)}
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4">
            <Label htmlFor="meetings-calendar-email" className="text-sm font-medium">
              Calendar
            </Label>
            <Input
              id="meetings-calendar-email"
              type="email"
              className="max-w-xs"
              value={calendarDraft}
              placeholder={optIn?.serviceAccountEmail ? 'me@gmail.com' : undefined}
              disabled={loading || saving}
              onChange={(e) => setCalendarDraft(e.target.value)}
              onBlur={() => void commitCalendar()}
            />
          </div>

          {optIn?.serviceAccountEmail && (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <span className="text-sm font-medium">Shared with</span>
              <span className="max-w-xs text-sm text-muted-foreground">
                <ClampedText text={optIn.serviceAccountEmail} lines={1} />
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {error && (
        <Card>
          <CardContent className="py-5 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {enabled ? (
        <ResourceList config={config} />
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-14">
            <p className="text-sm text-muted-foreground">No meetings.</p>
            <Button
              disabled={loading || saving}
              onClick={() => void toggleMaster(true)}
            >
              Record my meetings
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
