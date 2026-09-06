'use client';

/**
 * Server-searched contact picker options (review round 1, S2) - the
 * broadcasts module's audience/test-send contact pickers used to source
 * from `conversationService.listThreads`, which caps at the router's
 * default `page_size=50` with no search - a stand-in the S0 comment said
 * would be replaced once A2 merged. This hook sources from the real A2
 * contact list (`contactService.list`, server-side search) instead.
 *
 * Debounces the typed query and keeps every contact ever returned - across
 * searches AND the caller's already-selected ids - so a previously-picked
 * contact's label never disappears from a later, differently-filtered page
 * (a `MultiSelect`/`SearchSelect` only renders a label for ids present in
 * its current `options`).
 */
import { useEffect, useRef, useState } from 'react';
import { contactService } from '@/services/contact-service';
import type { ContactListItem } from '@/types/omnichannel';

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 250;
// Post-approval nit N2: the backend has no "get many contacts by id" route
// (the contact filter whitelist has no `id` column, `contactService.list`'s
// `search` is a name/phone substring match, not an id lookup) - a real batch
// call would need a new endpoint, out of scope for this fix. Cap the
// per-pass backfill instead of firing one GET per selected id unbounded: a
// realistic manual "Selected contacts" pick is small, and each selection
// change re-runs this effect, so a selection built up over several picks
// still converges - it just resolves in bounded chunks rather than one
// unbounded burst.
const MAX_BACKFILL_PER_PASS = 20;

export interface ContactPickerOption {
  label: string;
  value: string;
}

export interface UseContactPickerResult {
  query: string;
  setQuery: (query: string) => void;
  options: ContactPickerOption[];
  loading: boolean;
}

function toOption(c: ContactListItem): ContactPickerOption {
  return { label: c.phone ? `${c.name} (${c.phone})` : c.name, value: c.id };
}

export function useContactPicker(
  workspaceId: string | null,
  selectedIds: string[] = [],
): UseContactPickerResult {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const knownRef = useRef<Map<string, ContactListItem>>(new Map());
  const [, bumpVersion] = useState(0);

  useEffect(() => {
    if (!workspaceId) return undefined;
    let cancelled = false;
    setLoading(true);
    const handle = setTimeout(() => {
      contactService
        .list(workspaceId, { page: 0, pageSize: PAGE_SIZE, search: query.trim() || undefined })
        .then((result) => {
          if (cancelled) return;
          for (const c of result.data) knownRef.current.set(c.id, c);
          bumpVersion((n) => n + 1);
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [workspaceId, query]);

  const selectedKey = selectedIds.join(',');
  useEffect(() => {
    if (!workspaceId) return undefined;
    const missing = selectedIds.filter((id) => !knownRef.current.has(id)).slice(0, MAX_BACKFILL_PER_PASS);
    if (missing.length === 0) return undefined;
    let cancelled = false;
    Promise.all(missing.map((id) => contactService.get(workspaceId, id).catch(() => null))).then((rows) => {
      if (cancelled) return;
      for (const row of rows) if (row) knownRef.current.set(row.id, row);
      bumpVersion((n) => n + 1);
    });
    return () => {
      cancelled = true;
    };
    // `selectedKey` is the stable, comparable form of `selectedIds`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, selectedKey]);

  return {
    query,
    setQuery,
    options: Array.from(knownRef.current.values()).map(toOption),
    loading,
  };
}
