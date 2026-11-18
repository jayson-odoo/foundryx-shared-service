'use client';

/**
 * The allowed origins editor on the Embed access page with the Foundryx UIUX
 * switch on (slice W2-WS), self-save mode only. Same list rules and the same
 * save request as with the switch off (`onSave(list)`); what changes:
 * - "Save origins" is the page's red action while this tab is open, greyed
 *   with "Nothing changed yet." until the list changes (today's button is
 *   disabled the same way).
 * - A wrong origin says why under the field without moving anything.
 * - Saving ends with a done toast whose Undo saves the list as it was.
 */
import { useMemo, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { validateEmbedOrigin } from '@/lib/embed-origin';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxField } from '@/components/fx/fields';
import { useFxUserName } from '../workspaces/components/use-fx-user-name';

export interface FxOriginsEditorProps {
  origins: string[];
  onSave: (origins: string[]) => Promise<void>;
}

/** "1 origin" / "3 origins". */
export function fxOriginsCount(n: number): string {
  return n === 1 ? '1 origin' : `${n} origins`;
}

export function FxOriginsEditor({ origins, onSave }: FxOriginsEditorProps) {
  const byWhom = useFxUserName();
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

  const save = async () => {
    if (saving) return;
    const before = origins;
    setSaving(true);
    try {
      await onSave(list);
      toast.fxDone({
        what: 'Allowed origins saved',
        howMany: fxOriginsCount(list.length),
        byWhom,
        undo: () =>
          void onSave(before)
            .then(() => setList(before))
            .catch(() => toast.error("Couldn't undo. The new origins stay.")),
      });
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Couldn't save the origins.",
      );
    } finally {
      setSaving(false);
    }
  };
  const saveRef = useRef(save);
  saveRef.current = save;

  const main = useMemo<FxMainActionSpec>(
    () => ({
      id: 'save-origins',
      label: 'Save origins',
      fullLabel: dirty ? `Save ${fxOriginsCount(list.length)}` : undefined,
      onClick: () => void saveRef.current(),
      working: saving,
      blocked: dirty ? undefined : { reason: 'Nothing changed yet.' },
    }),
    [dirty, list.length, saving],
  );
  useRegisterMainAction(main);

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
      <CardContent className="py-1">
        <div className="flex flex-col gap-4 pb-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
            <FxField message={error} className="min-w-0 flex-1 pb-4 sm:pb-0">
              <Input
                placeholder="https://crm.acme.com"
                value={draft}
                aria-label="New allowed origin"
                aria-invalid={error ? true : undefined}
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
            </FxField>
            <Button
              type="button"
              variant="outline"
              onClick={add}
              disabled={!draft.trim()}
            >
              <Plus /> Add origin
            </Button>
          </div>

          {list.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {list.map((origin) => (
                <Badge
                  key={origin}
                  variant="secondary"
                  appearance="outline"
                  className="gap-1 font-mono"
                >
                  {origin}
                  <button
                    type="button"
                    aria-label={`Remove ${origin}`}
                    title="Remove"
                    className={cn(
                      PRESSED_CLASS,
                      'ms-0.5 rounded-sm text-(--fx-ink-3) hover:text-(--fx-act)',
                    )}
                    onClick={() => setList(list.filter((o) => o !== origin))}
                  >
                    <X className="size-3.5" />
                  </button>
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-sm text-(--fx-ink-3)">No origins added yet.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
