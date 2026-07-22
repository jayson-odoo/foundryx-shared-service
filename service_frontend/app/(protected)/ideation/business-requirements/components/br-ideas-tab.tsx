'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { LoaderCircleIcon, Plus, X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { MultiSelect } from '@/components/platform/multi-select';
import { useCan } from '@/hooks/use-can';
import { useBrIdeas } from '@/hooks/use-br-ideas';
import { businessRequirementService } from '@/services/business-requirement-service';
import { ideationService } from '@/services/ideation-service';
import type { Idea } from '@/types/ideation';

export interface BrIdeasTabProps {
  brId: string;
  /** The BR's product — a BR only links same-product ideas (AC-BI-17). */
  productId: string;
  reloadToken: number;
  /** Bumped after a link/unlink so the grill re-seeds from fresh source ideas
   * next turn (AC-BI-33) and the linked list reloads. */
  onChanged: () => void;
}

/** Ideas tab — the linked ideas feeding this BR (lineage, AC-BI-35) + link/unlink
 * (AC-BI-33: an idea linked mid-session re-seeds the grill's source context next
 * turn — the conversation is NOT restarted). Data via `useBrIdeas`
 * (UI → hook → service). Linking is gated by `.manage`. */
export function BrIdeasTab({ brId, productId, reloadToken, onChanged }: BrIdeasTabProps) {
  const { ideas } = useBrIdeas(brId, reloadToken);
  const { can } = useCan();
  const canManage = can('ideation.business_requirements.manage');

  if (ideas === null) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  return (
    <Card>
      <CardContent className="py-4 space-y-4">
        {canManage && (
          <LinkIdeas
            brId={brId}
            productId={productId}
            linked={ideas}
            onLinked={onChanged}
          />
        )}

        {ideas.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">No linked ideas.</p>
        ) : (
          <div className="divide-y divide-border">
            {ideas.map((idea) => (
              <LinkedRow
                key={idea.id}
                brId={brId}
                idea={idea}
                canManage={canManage}
                onUnlinked={onChanged}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LinkedRow({
  brId,
  idea,
  canManage,
  onUnlinked,
}: {
  brId: string;
  idea: Idea;
  canManage: boolean;
  onUnlinked: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const unlink = async () => {
    setBusy(true);
    try {
      await businessRequirementService.unlinkIdea(brId, idea.id);
      toast.success('Idea unlinked.');
      onUnlinked();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not unlink the idea.');
      setBusy(false);
    }
  };
  return (
    <div className="flex items-center justify-between gap-3 py-3">
      <Link
        href={`/ideation/ideas/${idea.id}`}
        className="min-w-0 flex-1 text-sm text-foreground line-clamp-2 hover:underline"
      >
        {idea.problem}
      </Link>
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-xs text-muted-foreground">{idea.submitterName}</span>
        <Badge variant="secondary">{idea.productName}</Badge>
        {canManage && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={unlink}
            aria-label="Unlink idea"
          >
            <X className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

function LinkIdeas({
  brId,
  productId,
  linked,
  onLinked,
}: {
  brId: string;
  productId: string;
  linked: Idea[];
  onLinked: () => void;
}) {
  const [candidates, setCandidates] = useState<Idea[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    ideationService
      .listIdeas()
      .then((all) => !cancelled && setCandidates(all))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [linked]);

  const linkedIds = useMemo(() => new Set(linked.map((i) => i.id)), [linked]);
  const options = useMemo(
    () =>
      candidates
        .filter((i) => i.productId === productId && !linkedIds.has(i.id))
        .map((i) => ({ value: i.id, label: i.problem })),
    [candidates, productId, linkedIds],
  );

  const link = async () => {
    if (selected.length === 0) return;
    setBusy(true);
    try {
      await businessRequirementService.linkIdeas(brId, selected);
      toast.success(selected.length === 1 ? 'Idea linked.' : `${selected.length} ideas linked.`);
      setSelected([]);
      onLinked();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not link ideas.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <MultiSelect
          options={options}
          value={selected}
          onChange={setSelected}
          placeholder="Link ideas from this product…"
        />
      </div>
      <Button onClick={link} disabled={busy || selected.length === 0} className="shrink-0">
        <Plus className="size-4" />
        Link
      </Button>
    </div>
  );
}
