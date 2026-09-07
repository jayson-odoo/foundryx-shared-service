'use client';

import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { validateEmbedOrigin } from '@/lib/embed-origin';
import { cn } from '@/lib/utils';

export interface OriginsEditorProps {
  origins: string[];
  /** Self-save mode (default, the embed settings screen): persist to the
   *  server on its own "Save origins" button. Omit when `onChange` is passed
   *  instead. */
  onSave?: (origins: string[]) => Promise<void>;
  /**
   * Controlled/staged mode (plan 34 / A7b connect wizard, AC-WEB-02): every
   * add/remove is reported to the parent immediately, no self-save button
   * renders, and the PARENT's own submit action (e.g. the wizard's
   * "Connect") persists the staged list together with the rest of its form.
   * Mutually exclusive with `onSave` - passing both is a caller error.
   */
  onChange?: (origins: string[]) => void;
  /** Hide the "No origins added yet." empty caption + the card chrome
   *  (title/description) - for embedding inside another card/step that
   *  already has its own heading (the connect wizard). */
  bare?: boolean;
}

/**
 * Add/remove editor for the allowed parent origins. Client-mirrors the server
 * validation for instant feedback (server is the boundary). Two modes: self-
 * save (`onSave`, the embed settings screen's own persisted list) or
 * controlled/staged (`onChange`, the plan 34 connect wizard - no origins to
 * persist until the channel itself is created).
 */
export function OriginsEditor({ origins, onSave, onChange, bare }: OriginsEditorProps) {
  const [list, setList] = useState<string[]>(origins);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const dirty =
    list.length !== origins.length || list.some((o, i) => o !== origins[i]);

  const commit = (next: string[]) => {
    setList(next);
    onChange?.(next);
  };

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
    commit([...list, check.value]);
    setDraft('');
    setError(null);
  };

  const remove = (origin: string) => {
    commit(list.filter((o) => o !== origin));
  };

  const save = async () => {
    if (!onSave) return;
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

  const body = (
    <div className="flex flex-col gap-4">
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
                className={cn(PRESSED_CLASS, 'ms-0.5 rounded-sm text-muted-foreground hover:text-foreground')}
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

      {onSave && (
        <div>
          <Button onClick={() => void save()} disabled={saving || !dirty}>
            {saving ? 'Saving…' : 'Save origins'}
          </Button>
        </div>
      )}
    </div>
  );

  if (bare) return body;

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
      <CardContent className="py-1">{body}</CardContent>
    </Card>
  );
}
