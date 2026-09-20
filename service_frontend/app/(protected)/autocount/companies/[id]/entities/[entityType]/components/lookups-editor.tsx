'use client';

import { useCallback } from 'react';
import { ArrowDown, ArrowUp, Play, Plus, Trash2 } from 'lucide-react';
import type {
  AutocountLookupField,
  AutocountLookupJoinPair,
  AutocountLookupMatch,
  AutocountLookupPreviewResult,
  AutocountLookupSpec,
} from '@/types/autocount';
import {
  aliasCollision,
  canTestLookup,
  emptyLookup,
  localColumnOptions,
  MAX_LOOKUPS,
  validateLookupPath,
} from '@/lib/autocount-lookups';
import type { UsePreviewColumnsMapResult } from '@/hooks/use-autocount-pull';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';

const MATCH_OPTIONS: { label: string; value: AutocountLookupMatch }[] = [
  { label: 'Exact', value: 'exact' },
  { label: 'Ignore case and spaces', value: 'casefold_trim' },
];

export interface LookupsEditorProps {
  editing: boolean;
  lookups: AutocountLookupSpec[];
  onChange: (lookups: AutocountLookupSpec[]) => void;
  /** The task's own previewed SOURCE columns (never a lookup alias). */
  sourceColumns: string[];
  connectionId: string | null;
  columnsProbe: UsePreviewColumnsMapResult;
  /**
   * Per-lookup matched/missed from the LAST combined Test (the main Source
   * tab Test button, run with `lookups` attached) - a SAMPLE count
   * (BL-SS-222), labelled as such rather than "the" enrich-miss rate.
   */
  lookupResults?: AutocountLookupPreviewResult[];
}

function probeKey(rowKey: string): string {
  return `lookup:${rowKey}`;
}

/**
 * The Source tab's Lookups section (R9, AC-10-01/09) - operator-authored,
 * ordered cross-endpoint joins. Add / remove / reorder; every dropdown is
 * searchable; nothing free text except the path and the alias.
 */
export function LookupsEditor({
  editing,
  lookups,
  onChange,
  sourceColumns,
  connectionId,
  columnsProbe,
  lookupResults = [],
}: LookupsEditorProps) {
  const updateLookup = useCallback(
    (index: number, patch: Partial<AutocountLookupSpec>) => {
      onChange(lookups.map((l, i) => (i === index ? { ...l, ...patch } : l)));
    },
    [lookups, onChange],
  );

  const addLookup = useCallback(() => {
    onChange([...lookups, emptyLookup(lookups.length)]);
  }, [lookups, onChange]);

  const removeLookup = useCallback(
    (index: number) => {
      onChange(lookups.filter((_, i) => i !== index));
    },
    [lookups, onChange],
  );

  const moveLookup = useCallback(
    (index: number, direction: -1 | 1) => {
      const target = index + direction;
      if (target < 0 || target >= lookups.length) return;
      const next = [...lookups];
      const [moved] = next.splice(index, 1);
      next.splice(target, 0, moved);
      onChange(next);
    },
    [lookups, onChange],
  );

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-sm font-semibold">Lookups</Label>
        {editing && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addLookup}
            disabled={lookups.length >= MAX_LOOKUPS}
            data-testid="lookups-add"
          >
            <Plus className="size-3.5" />
            Add lookup
          </Button>
        )}
      </div>

      {lookups.length === 0 ? (
        <p className="text-sm text-muted-foreground">No lookups configured.</p>
      ) : (
        lookups.map((lookup, index) => {
          const rowKey = `${index}`;
          const key = probeKey(rowKey);
          const probedColumns = columnsProbe.columnsByKey[key] ?? [];
          const probing = columnsProbe.loadingKeys[key] ?? false;
          const probeError = columnsProbe.errorsByKey[key];
          const pathError = validateLookupPath(lookup.path);
          const result = lookupResults.find((r) => r.alias === lookup.as);
          const localOptions = localColumnOptions(
            sourceColumns,
            lookups,
            index,
          ).map((c) => ({
            label: c,
            value: c,
          }));
          const remoteOptions = probedColumns.map((c) => ({
            label: c,
            value: c,
          }));

          return (
            <div
              key={rowKey}
              className="flex flex-col gap-3 rounded-md border border-border p-3"
              data-testid={`lookup-row-${index}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary" appearance="light" size="sm">
                  #{index + 1}
                </Badge>
                <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-md">
                  <Input
                    value={lookup.path}
                    onChange={(e) =>
                      updateLookup(index, { path: e.target.value })
                    }
                    disabled={!editing}
                    placeholder="/itemuombypage"
                    className="font-mono"
                    aria-label={`Lookup ${index + 1} endpoint path`}
                    aria-invalid={
                      editing && Boolean(lookup.path) && Boolean(pathError)
                    }
                  />
                  {editing && lookup.path && pathError && (
                    <p className="text-xs text-destructive">{pathError}</p>
                  )}
                </div>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  disabled={!editing || !connectionId || !canTestLookup(lookup)}
                  onClick={() =>
                    connectionId &&
                    void columnsProbe.run(key, connectionId, lookup.path)
                  }
                  data-testid={`lookup-test-${index}`}
                >
                  <Play className="size-3.5" />
                  Test
                </Button>
                {probing && (
                  <span className="text-xs text-muted-foreground">
                    Probing…
                  </span>
                )}
                {!probing && probedColumns.length > 0 && (
                  <Badge variant="success" appearance="light" size="sm">
                    {probedColumns.length} columns
                  </Badge>
                )}
                {result && (
                  <Badge
                    variant="info"
                    appearance="light"
                    size="sm"
                    data-testid={`lookup-result-${index}`}
                  >
                    Sample: {result.matched} matched · {result.missed} missed
                  </Badge>
                )}
                {editing && (
                  <div className="ms-auto flex items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      disabled={index === 0}
                      onClick={() => moveLookup(index, -1)}
                      aria-label={`Move lookup ${index + 1} up`}
                    >
                      <ArrowUp className="size-3.5" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      disabled={index === lookups.length - 1}
                      onClick={() => moveLookup(index, 1)}
                      aria-label={`Move lookup ${index + 1} down`}
                    >
                      <ArrowDown className="size-3.5" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      onClick={() => removeLookup(index)}
                      aria-label={`Remove lookup ${index + 1}`}
                      data-testid={`lookup-remove-${index}`}
                    >
                      <Trash2 className="size-3.5 text-destructive" />
                    </Button>
                  </div>
                )}
              </div>
              {probeError && (
                <p className="text-xs text-destructive">{probeError}</p>
              )}

              <JoinPairsEditor
                editing={editing}
                pairs={lookup.on}
                localOptions={localOptions}
                remoteOptions={remoteOptions}
                onChange={(on) => updateLookup(index, { on })}
              />

              <FieldsEditor
                editing={editing}
                fields={lookup.fields}
                remoteOptions={remoteOptions}
                sourceColumns={sourceColumns}
                lookups={lookups}
                lookupIndex={index}
                onChange={(fields) => updateLookup(index, { fields })}
              />
            </div>
          );
        })
      )}
    </div>
  );
}

interface JoinPairsEditorProps {
  editing: boolean;
  pairs: AutocountLookupJoinPair[];
  localOptions: { label: string; value: string }[];
  remoteOptions: { label: string; value: string }[];
  onChange: (pairs: AutocountLookupJoinPair[]) => void;
}

function JoinPairsEditor({
  editing,
  pairs,
  localOptions,
  remoteOptions,
  onChange,
}: JoinPairsEditorProps) {
  return (
    <div className="flex flex-col gap-2">
      <Label className="text-xs text-muted-foreground">Join on</Label>
      {pairs.map((pair, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <SearchSelect
            options={localOptions}
            value={pair.local}
            onChange={(local) =>
              onChange(pairs.map((p, j) => (j === i ? { ...p, local } : p)))
            }
            placeholder="This task's column"
            disabled={!editing}
            ariaLabel="Local column"
            className="min-w-40"
          />
          <span className="text-xs text-muted-foreground">=</span>
          <SearchSelect
            options={remoteOptions}
            value={pair.remote}
            onChange={(remote) =>
              onChange(pairs.map((p, j) => (j === i ? { ...p, remote } : p)))
            }
            placeholder="Remote column"
            disabled={!editing}
            ariaLabel="Remote column"
            className="min-w-40"
          />
          <SearchSelect
            options={MATCH_OPTIONS}
            value={pair.match ?? 'exact'}
            onChange={(match) =>
              onChange(
                pairs.map((p, j) =>
                  j === i ? { ...p, match: match as AutocountLookupMatch } : p,
                ),
              )
            }
            disabled={!editing}
            ariaLabel="Match mode"
            className="min-w-44"
          />
          {editing && pairs.length > 1 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              mode="icon"
              onClick={() => onChange(pairs.filter((_, j) => j !== i))}
              aria-label={`Remove join pair ${i + 1}`}
            >
              <Trash2 className="size-3.5 text-destructive" />
            </Button>
          )}
        </div>
      ))}
      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          onClick={() => onChange([...pairs, { local: '', remote: '' }])}
        >
          <Plus className="size-3.5" />
          Add join
        </Button>
      )}
    </div>
  );
}

interface FieldsEditorProps {
  editing: boolean;
  fields: AutocountLookupField[];
  remoteOptions: { label: string; value: string }[];
  sourceColumns: string[];
  lookups: AutocountLookupSpec[];
  lookupIndex: number;
  onChange: (fields: AutocountLookupField[]) => void;
}

function FieldsEditor({
  editing,
  fields,
  remoteOptions,
  sourceColumns,
  lookups,
  lookupIndex,
  onChange,
}: FieldsEditorProps) {
  return (
    <div className="flex flex-col gap-2">
      <Label className="text-xs text-muted-foreground">Bring in fields</Label>
      {fields.map((field, i) => {
        const error = field.as
          ? aliasCollision(field.as, sourceColumns, lookups, lookupIndex, i)
          : null;
        return (
          <div key={i} className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <SearchSelect
                options={remoteOptions}
                value={field.remote}
                onChange={(remote) =>
                  onChange(
                    fields.map((f, j) => (j === i ? { ...f, remote } : f)),
                  )
                }
                placeholder="Remote column"
                disabled={!editing}
                ariaLabel="Remote field"
                className="min-w-40"
              />
              <span className="text-xs text-muted-foreground">as</span>
              <Input
                value={field.as}
                onChange={(e) =>
                  onChange(
                    fields.map((f, j) =>
                      j === i ? { ...f, as: e.target.value } : f,
                    ),
                  )
                }
                disabled={!editing}
                placeholder="BaseUOMPrice"
                className="w-44 font-mono"
                aria-label="Field alias"
                aria-invalid={Boolean(error)}
              />
              {editing && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  mode="icon"
                  onClick={() => onChange(fields.filter((_, j) => j !== i))}
                  aria-label={`Remove field ${i + 1}`}
                >
                  <Trash2 className="size-3.5 text-destructive" />
                </Button>
              )}
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        );
      })}
      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          onClick={() => onChange([...fields, { remote: '', as: '' }])}
        >
          <Plus className="size-3.5" />
          Add field
        </Button>
      )}
    </div>
  );
}
