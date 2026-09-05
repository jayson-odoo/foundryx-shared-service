'use client';

/**
 * Contact panel - Tags section (plan 25, AC-CDM-35/38). Chips (emoji + colour
 * + name) with a remove ×; "Add tag" offers ONLY the workspace's tags the
 * contact does NOT already carry (foolproof-UI). Optimistic add/remove -
 * reconciles with the PATCH response, reverting the chip set on error.
 */
import { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { SearchSelect } from '@/components/platform/search-select';
import { ApiError } from '@/lib/api-client';
import { useCan } from '@/hooks/use-can';
import type { ContactTag, ContactTagRef } from '@/types/omnichannel';

export interface TagChipsProps {
  tags: ContactTagRef[];
  workspaceTags: ContactTag[];
  onChange: (tagIds: string[]) => Promise<unknown>;
}

export function TagChips({ tags, workspaceTags, onChange }: TagChipsProps) {
  const { can } = useCan();
  const canManage = can('contacts.manage');
  const [optimistic, setOptimistic] = useState<ContactTagRef[] | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = optimistic ?? tags;

  // A fresh authoritative `tags` array (server reconcile, a real WS push, or a
  // different contact) always wins - drop the optimistic overlay once it
  // arrives so a resolved server state can never be masked by a stale one.
  useEffect(() => {
    setOptimistic(null);
  }, [tags]);

  const available = useMemo(
    () => workspaceTags.filter((wt) => !shown.some((t) => t.id === wt.id)),
    [workspaceTags, shown],
  );

  const apply = async (nextIds: string[], nextRefs: ContactTagRef[]) => {
    setOptimistic(nextRefs);
    setBusy(true);
    try {
      await onChange(nextIds);
    } catch (error) {
      // F4 (plan-25 round-3 codex triage): clear the overlay, don't revert to
      // the `tags` snapshot captured when this call STARTED - a WS push that
      // landed while the PATCH was in flight already made `tags` (the prop)
      // authoritative; reverting to the stale closed-over value would
      // clobber it. `shown = optimistic ?? tags` then falls through to
      // whatever `tags` IS right now.
      setOptimistic(null);
      toast.error(error instanceof ApiError ? error.message : 'Could not update tags.');
    } finally {
      setBusy(false);
    }
  };

  const addTag = (tagId: string) => {
    const tag = workspaceTags.find((t) => t.id === tagId);
    if (!tag) return;
    const nextRefs = [...shown, { id: tag.id, name: tag.name, emoji: tag.emoji, color: tag.color }];
    void apply(
      nextRefs.map((t) => t.id),
      nextRefs,
    );
  };

  const removeTag = (tagId: string) => {
    const nextRefs = shown.filter((t) => t.id !== tagId);
    void apply(
      nextRefs.map((t) => t.id),
      nextRefs,
    );
  };

  return (
    <div className="flex flex-col gap-2" data-testid="tag-chips-section">
      <p className="text-xs font-medium text-muted-foreground uppercase">Tags</p>
      <div className="flex flex-wrap gap-1.5">
        {shown.length === 0 && <p className="text-sm text-muted-foreground">No tags yet.</p>}
        {shown.map((tag) => (
          <Badge
            key={tag.id}
            variant="secondary"
            appearance="light"
            size="sm"
            style={tag.color ? { backgroundColor: `${tag.color}22`, color: tag.color } : undefined}
            className="gap-1"
          >
            {tag.emoji && <span aria-hidden>{tag.emoji}</span>}
            {tag.name}
            {canManage && (
              <button
                type="button"
                aria-label={`Remove ${tag.name}`}
                onClick={() => removeTag(tag.id)}
                disabled={busy}
                className="ms-0.5 rounded-full hover:opacity-70"
              >
                <X className="size-3" />
              </button>
            )}
          </Badge>
        ))}
      </div>
      {canManage && available.length > 0 && (
        <SearchSelect
          options={available.map((t) => ({ label: `${t.emoji ? `${t.emoji} ` : ''}${t.name}`, value: t.id }))}
          value={null}
          onChange={addTag}
          placeholder="Add tag…"
          ariaLabel="Add tag"
          disabled={busy}
        />
      )}
    </div>
  );
}
