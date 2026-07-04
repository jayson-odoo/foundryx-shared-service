'use client';

/** Reusable name-list editor for a template's roles / segments (AC-11-01).
 * Read-only shows the names; the Edit toggle reveals an add row + per-item
 * delete. Tiny master data — no Resource shell needed. */
import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { TemplateChild } from '@/types/ems';

export interface ChildListEditorProps {
  items: TemplateChild[];
  editing: boolean;
  emptyLabel: string;
  addPlaceholder: string;
  onAdd: (name: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export function ChildListEditor({
  items,
  editing,
  emptyLabel,
  addPlaceholder,
  onAdd,
  onDelete,
}: ChildListEditorProps) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  const add = async () => {
    const v = name.trim();
    if (!v) return;
    setBusy(true);
    try {
      await onAdd(v);
      setName('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex max-w-xl flex-col gap-3 py-2">
      {editing && (
        <div className="flex items-center gap-2">
          <Input
            value={name}
            placeholder={addPlaceholder}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void add();
              }
            }}
          />
          <Button onClick={() => void add()} disabled={!name.trim() || busy}>
            <Plus /> Add
          </Button>
        </div>
      )}

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyLabel}</p>
      ) : (
        <ul className="flex flex-col divide-y rounded-md border">
          {items.map((it) => (
            <li key={it.id} className="flex items-center justify-between gap-2 px-3 py-2">
              <span className="text-sm font-medium">{it.name}</span>
              {editing && (
                <Button
                  variant="ghost"
                  size="sm"
                  mode="icon"
                  className="text-destructive hover:text-destructive"
                  aria-label={`Delete ${it.name}`}
                  onClick={() => void onDelete(it.id)}
                >
                  <Trash2 />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
