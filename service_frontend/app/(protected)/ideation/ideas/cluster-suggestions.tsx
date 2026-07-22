'use client';

import { useState } from 'react';
import { LoaderCircleIcon, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { ClampedText } from '@/components/platform/clamped-text';
import { useCan } from '@/hooks/use-can';
import { ideationService } from '@/services/ideation-service';
import type { Idea, IdeaCluster } from '@/types/ideation';

export interface IdeaClusterSuggestionsProps {
  /** Promote the (edited) selection of a cluster to a new draft BR. `meta.title`
   * carries the cluster label so the new BR is named after the cluster
   * (AC-BI-32b). */
  onPromote: (ideas: Idea[], meta?: { title?: string }) => Promise<void>;
}

/**
 * Cluster suggestions (AC-BI-30/31) — on-demand trigram+LLM grouping surfaced
 * above the ideas list. Each suggested cluster is FULLY EDITABLE before
 * promotion: deselect ideas, or promote a single idea alone. Nothing
 * auto-promotes. Gated by `ideation.clusters.manage` (Triager); hidden entirely
 * without it.
 */
export function IdeaClusterSuggestions({ onPromote }: IdeaClusterSuggestionsProps) {
  const { can } = useCan();
  const [clusters, setClusters] = useState<IdeaCluster[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  if (!can('ideation.clusters.manage')) return null;

  const findClusters = async () => {
    setLoading(true);
    setOpen(true);
    try {
      const res = await ideationService.suggestClusters();
      setClusters(res.clusters);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not suggest clusters.');
      setClusters([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mb-4">
      {!open ? (
        <Button variant="outline" size="sm" onClick={findClusters}>
          <Sparkles className="size-4" />
          Suggest clusters
        </Button>
      ) : (
        <Card>
          <CardContent className="py-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Sparkles className="size-4 text-primary" />
                Suggested clusters
              </div>
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                Hide
              </Button>
            </div>

            {loading ? (
              <div className="flex items-center justify-center py-8 text-muted-foreground">
                <LoaderCircleIcon className="size-5 animate-spin" />
              </div>
            ) : clusters && clusters.length > 0 ? (
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {clusters.map((cluster, i) => (
                  <ClusterCard key={i} cluster={cluster} onPromote={onPromote} />
                ))}
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No clusters found.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ClusterCard({
  cluster,
  onPromote,
}: {
  cluster: IdeaCluster;
  onPromote: (ideas: Idea[], meta?: { title?: string }) => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(cluster.ideaIds),
  );
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const promote = async () => {
    const chosen = cluster.ideas.filter((i) => selected.has(i.id));
    if (chosen.length === 0) return;
    setBusy(true);
    try {
      await onPromote(chosen, { title: cluster.label });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{cluster.label}</span>
        <Badge variant="secondary">{cluster.ideas[0]?.productName}</Badge>
      </div>
      <div className="space-y-1.5">
        {cluster.ideas.map((idea) => (
          <label
            key={idea.id}
            className="flex cursor-pointer items-start gap-2 text-sm text-foreground"
          >
            <Checkbox
              checked={selected.has(idea.id)}
              onCheckedChange={() => toggle(idea.id)}
              className="mt-0.5"
            />
            <span className="min-w-0 flex-1">
              <ClampedText text={idea.problem} lines={2} />
            </span>
          </label>
        ))}
      </div>
      <div className="mt-3 flex justify-end">
        <Button size="sm" onClick={promote} disabled={busy || selected.size === 0}>
          Promote {selected.size} to BR
        </Button>
      </div>
    </div>
  );
}
