'use client';

/**
 * The CSV-mode contacts header map (S6, AC-MIG-47, plan §5.6) - one
 * `SearchSelect` per system field key (`MIGRATION_CSV_HEADER_KEYS`, a fixed
 * small set) offering the UPLOADED file's own headers as options, plus "Not
 * mapped". A key left "Not mapped" is not an error - the backend's own
 * case-insensitive alias guess (`_HEADER_ALIASES`) fills in what the
 * operator left unset (plan §5.6's own stated invariant: a vendor header
 * rename is a mapping click, never a code change).
 */
import { SearchSelect } from '@/components/platform/search-select';
import { MIGRATION_CSV_HEADER_KEYS } from '@/types/respondio-migration';

const NOT_MAPPED = '__not_mapped__';

export function CsvHeaderMapSection({
  headers,
  value,
  editing,
  onChange,
}: {
  headers: string[];
  value: Record<string, string>;
  editing: boolean;
  onChange: (next: Record<string, string>) => void;
}) {
  if (headers.length === 0) return null;
  const options = [{ label: 'Not mapped', value: NOT_MAPPED }, ...headers.map((h) => ({ label: h, value: h }))];

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">Contacts CSV columns</p>
      {MIGRATION_CSV_HEADER_KEYS.map(({ key, label }) => (
        <div key={key} className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <p className="min-w-0 truncate text-sm">{label}</p>
          <div className="w-full sm:max-w-xs">
            <SearchSelect
              ariaLabel={`File column for ${label}`}
              options={options}
              value={value[key] ?? NOT_MAPPED}
              disabled={!editing}
              onChange={(next) => {
                const copy = { ...value };
                if (next === NOT_MAPPED) delete copy[key];
                else copy[key] = next;
                onChange(copy);
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
