'use client';

import { useCallback, useEffect, useState } from 'react';
import { meetingsService } from '@/services/meetings-service';
import type { MeetingsEvent, MeetingsOptIn } from '@/types/meetings';

export interface UseMyMeetings {
  optIn: MeetingsOptIn | null;
  events: MeetingsEvent[];
  loading: boolean;
  /** True while a toggle write is in flight — the switches disable themselves. */
  saving: boolean;
  error: string | null;
  reload: () => Promise<void>;
  setEnabled: (enabled: boolean) => Promise<void>;
  /** Point the sync at a different calendar; null = back to the login email. */
  setCalendarEmail: (calendarEmail: string | null) => Promise<void>;
  setEventOptOut: (eventId: string, optedOut: boolean) => Promise<void>;
}

/**
 * The caller's master toggle plus their upcoming events (S0 plan §4).
 *
 * The page reads meetings ONLY through this hook — no component touches the
 * service or api-client. The events read is skipped while the master toggle is
 * off, because nothing is synced for an opted-out user (AC-S0-9).
 */
export function useMyMeetings(): UseMyMeetings {
  const [optIn, setOptIn] = useState<MeetingsOptIn | null>(null);
  const [events, setEvents] = useState<MeetingsEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const state = await meetingsService.getOptIn();
      setOptIn(state);
      setEvents(state.enabled ? await meetingsService.listEvents() : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load meetings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setEnabled = useCallback(
    async (enabled: boolean) => {
      setSaving(true);
      setError(null);
      try {
        const state = await meetingsService.setOptIn({ enabled });
        setOptIn(state);
        setEvents(state.enabled ? await meetingsService.listEvents() : []);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not save the change.');
        throw e;
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  const setCalendarEmail = useCallback(
    async (calendarEmail: string | null) => {
      setSaving(true);
      setError(null);
      try {
        // Enabled travels with it: the write is one PUT and the toggle is
        // whatever it already is, never a value this call gets to change.
        const current = optIn?.enabled ?? false;
        const state = await meetingsService.setOptIn({ enabled: current, calendarEmail });
        setOptIn(state);
        // A different calendar is a different set of events, so re-read rather
        // than leave the old calendar's rows on screen.
        setEvents(state.enabled ? await meetingsService.listEvents() : []);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not save the change.');
        throw e;
      } finally {
        setSaving(false);
      }
    },
    [optIn],
  );

  const setEventOptOut = useCallback(async (eventId: string, optedOut: boolean) => {
    setSaving(true);
    setError(null);
    try {
      const updated = await meetingsService.setEventOptOut(eventId, optedOut);
      setEvents((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the change.');
      throw e;
    } finally {
      setSaving(false);
    }
  }, []);

  return {
    optIn,
    events,
    loading,
    saving,
    error,
    reload,
    setEnabled,
    setCalendarEmail,
    setEventOptOut,
  };
}
