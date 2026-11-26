'use client';

import { useMemo } from 'react';
import { SearchSelect } from '@/components/platform/search-select';
import { useAutocountLineNotesConnections } from '@/hooks/use-autocount-line-notes-connections';
import type { AutocountCompany } from '@/types/autocount';
import { DetailRow } from './detail-row';

/** The clear option's value (a SearchSelect value is always a string). */
const NONE = '';
const NOT_FOUND = 'Connection not found';

export interface LineNotesSectionProps {
  /** The persisted company - read mode renders from this. */
  company: AutocountCompany;
  /** The form's global Edit toggle. */
  editing: boolean;
  /** Working value (lifted to the parent so the form owns dirty + save). */
  connectionId: string | null;
  onChange: (id: string | null) => void;
  /** The plain message of a rejected save, shown next to the field. */
  error: string | null;
}

/**
 * The company's line notes database (plan 74): the `sql_database` connection the PO line notes are read
 * through. Only for a company that can write; saved through the Overview form's single save.
 */
export function LineNotesSection(props: LineNotesSectionProps) {
  // The connections are only fetched for a company that can write (the hook mounts with the field).
  return props.company.writeEnabled ? <LineNotesField {...props} /> : null;
}

function LineNotesField({
  company,
  editing,
  connectionId,
  onChange,
  error,
}: LineNotesSectionProps) {
  const { options, isLoading } = useAutocountLineNotesConnections();

  // A saved connection that is no longer listed (deleted) is shown as such, never as unset.
  const missing = (id: string | null): boolean =>
    !!id && !isLoading && !options.some((o) => o.value === id);

  const readLabel = useMemo(() => {
    if (!company.lineNotesConnectionId) return '-';
    const match = options.find((o) => o.value === company.lineNotesConnectionId);
    return match?.label ?? (isLoading ? '-' : NOT_FOUND);
  }, [company.lineNotesConnectionId, isLoading, options]);

  const choices = useMemo(
    () => [
      { label: 'None', value: NONE },
      ...(missing(connectionId) && connectionId ? [{ label: NOT_FOUND, value: connectionId }] : []),
      ...options,
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [connectionId, isLoading, options],
  );

  return (
    <DetailRow label="Line notes database">
      {editing ? (
        <div className="flex flex-col gap-2">
          <SearchSelect
            options={choices}
            value={connectionId ?? NONE}
            onChange={(value) => onChange(value === NONE ? null : value)}
            disabled={isLoading}
            ariaLabel="Line notes database"
          />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
      ) : (
        readLabel
      )}
    </DetailRow>
  );
}
