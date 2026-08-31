'use client';

import { useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
import type { AutocountEntityConfig } from '@/types/autocount';
import { AC_NEW_MASTER_ENTITY_TYPES, entityLabel } from '../../components/autocount-meta';

export interface AddEntityControlProps {
  entities: AutocountEntityConfig[];
  onAdd: (entityType: string) => void;
}

/**
 * Configure a NEW entity for this company (plan 22 S4, AC-22-23). Every entity
 * this build can extract via a database task starts with NO row at all - the
 * row is born when the task editor's first query save runs (``update_task``
 * "a row that exists ONLY for the DB path is born on the DB source") - so the
 * picker offers only the entities NOT already configured (foolproof-UI: only
 * valid options), and choosing one just opens that entity's task editor.
 */
export function AddEntityControl({ entities, onAdd }: AddEntityControlProps) {
  const [value, setValue] = useState<string | null>(null);
  const configured = useMemo(() => new Set(entities.map((e) => e.entityType)), [entities]);
  const options = useMemo(
    () =>
      AC_NEW_MASTER_ENTITY_TYPES.filter((entityType) => !configured.has(entityType)).map(
        (entityType) => ({ value: entityType, label: entityLabel(entityType) }),
      ),
    [configured],
  );

  if (options.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchSelect
        options={options}
        value={value}
        onChange={setValue}
        ariaLabel="Add entity"
        placeholder="Add entity"
        className="w-56"
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!value}
        data-testid="add-entity-configure"
        onClick={() => {
          if (!value) return;
          onAdd(value);
          setValue(null);
        }}
      >
        <Plus className="size-4" />
        Configure
      </Button>
    </div>
  );
}
