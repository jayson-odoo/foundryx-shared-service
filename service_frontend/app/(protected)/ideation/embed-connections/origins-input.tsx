'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';

/**
 * Multi-origin chip input for the embed connection's parent-origin allow-list.
 * Type an origin + Enter (or comma) to add a chip; the X removes one. Kept simple
 * and self-contained — the list is short (one or two host origins per tenant).
 */
export function OriginsInput({
  value,
  onChange,
  id,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  id?: string;
}) {
  const [draft, setDraft] = useState('');

  const add = () => {
    const trimmed = draft.trim().replace(/,$/, '').trim();
    if (!trimmed || value.includes(trimmed)) {
      setDraft('');
      return;
    }
    onChange([...value, trimmed]);
    setDraft('');
  };

  const remove = (origin: string) => onChange(value.filter((o) => o !== origin));

  return (
    <div className="flex flex-col gap-2">
      <Input
        id={id}
        value={draft}
        placeholder="https://app.example.com — press Enter to add"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
      />
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((origin) => (
            <Badge key={origin} variant="secondary" className="gap-1 font-mono text-xs">
              {origin}
              <button
                type="button"
                aria-label={`Remove ${origin}`}
                onClick={() => remove(origin)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
