'use client';

import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { validateEmbedOrigin } from '@/lib/embed-origin';

export interface OriginsEditorProps {
  origins: string[];
  onSave: (origins: string[]) => Promise<void>;
}

/**
 * Add/remove editor for the allowed parent origins. Client-mirrors the server
 * validation for instant feedback (server is the boundary). Changes are staged
 * locally and persisted with Save.
 */
export function OriginsEditor({ origins, onSave }: OriginsEditorProps) {
  const [list, setList] = useState<string[]>(origins);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const dirty =
    list.length !== origins.length || list.some((o, i) => o !== origins[i]);

  const add = () => {
    const check = validateEmbedOrigin(draft);
    if (!check.ok || !check.value) {
      setError(check.error ?? 'Invalid origin.');
      return;
    }
    if (list.includes(check.value)) {
      setError('That origin is already added.');
      return;
    }
    setList([...list, check.value]);
    setDraft('');
    setError(null);
  };

  const remove = (origin: string) => {
    setList(list.filter((o) => o !== origin));
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(list);
      toast.success('Allowed origins saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save origins.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Allowed origins</CardTitle>
          <CardDescription>
            The exact parent sites permitted to embed the widget.
          </CardDescription>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <Input
              placeholder="https://crm.acme.com"
              value={draft}
              aria-label="New allowed origin"
              onChange={(e) => {
                setDraft(e.target.value);
                if (error) setError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  add();
                }
              }}
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
          <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
            <Plus /> Add
          </Button>
        </div>

        {list.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {list.map((origin) => (
              <Badge key={origin} variant="secondary" appearance="outline" className="gap-1 font-mono">
                {origin}
                <button
                  type="button"
                  aria-label={`Remove ${origin}`}
                  className="ms-0.5 rounded-sm text-muted-foreground hover:text-foreground"
                  onClick={() => remove(origin)}
                >
                  <X className="size-3.5" />
                </button>
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No origins added yet.</p>
        )}

        <div>
          <Button onClick={() => void save()} disabled={saving || !dirty}>
            {saving ? 'Saving…' : 'Save origins'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
