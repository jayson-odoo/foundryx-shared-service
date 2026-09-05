'use client';

/**
 * Contact panel - Lifecycle section (plan 25, AC-CDM-35/37). Shows the current
 * stage badge (emoji label as authored on the canvas) and a "Move to" picker
 * listing ONLY the fireable outgoing edges (foolproof-UI - never an option
 * that would 409). Empty when the stage is terminal (won) or moves haven't
 * loaded yet.
 */
import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { SearchSelect } from '@/components/platform/search-select';
import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import { ApiError } from '@/lib/api-client';
import { useLifecycleMoves } from '@/hooks/use-lifecycle-moves';
import { useCan } from '@/hooks/use-can';
import type { ContactLifecycleSummary } from '@/types/omnichannel';

export interface LifecycleMoveProps {
  contactId: string;
  lifecycle: ContactLifecycleSummary | null;
  onMove: (toStatusId: string) => Promise<unknown>;
  /** F5 (plan-25 round-3 codex triage): a fingerprint of the OTHER
   *  condition-relevant contact fields (priority/assignee/CSW/…) - refetches
   *  the fireable-moves list even when the stage itself hasn't changed. */
  changeSignal?: string | null;
}

export function LifecycleMove({ contactId, lifecycle, onMove, changeSignal }: LifecycleMoveProps) {
  const { can } = useCan();
  const canManage = can('contacts.manage');
  const { moves, loading, refetch } = useLifecycleMoves(contactId, lifecycle?.key, changeSignal);
  const [moving, setMoving] = useState(false);

  if (!lifecycle) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-muted-foreground uppercase">Lifecycle</p>
        <p className="text-sm text-muted-foreground">Not available yet.</p>
      </div>
    );
  }

  const registry: StatusRegistry<string> = {
    [lifecycle.key]: { label: lifecycle.label, tone: 'secondary', hex: lifecycle.color ?? undefined },
  };

  const runMove = async (toStatusId: string) => {
    setMoving(true);
    try {
      await onMove(toStatusId);
    } catch (error) {
      if (error instanceof ApiError) {
        // A 409 carries a structured `detail = {code, message}` (the machine
        // message, e.g. "No move from Customer.") - api-client only promotes a
        // STRING detail to `message`, so read the structured message directly
        // (F14, AC-CDM-37). Falls back to the generic HTTP message otherwise.
        const d = error.detail as { message?: string } | undefined;
        toast.error(d?.message ?? error.message);
        // F5: a 409 means the cached fireable list already disagreed with
        // the server (e.g. a condition-gated edge closed between load and
        // click) - refetch so the picker doesn't keep offering it.
        if (error.status === 409) refetch();
      } else {
        toast.error('Could not move this contact.');
      }
    } finally {
      setMoving(false);
    }
  };

  return (
    <div className="flex flex-col gap-2" data-testid="lifecycle-section">
      <p className="text-xs font-medium text-muted-foreground uppercase">Lifecycle</p>
      <div className="flex items-center gap-2">
        <StatusBadge status={lifecycle.key} registry={registry} />
        {moving && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
      </div>
      {canManage && !loading && moves.length > 0 && (
        <SearchSelect
          options={moves.map((m) => ({ label: m.label, value: m.toStatusId }))}
          value={null}
          onChange={(v) => void runMove(v)}
          placeholder="Move to…"
          ariaLabel="Move to"
          disabled={moving}
        />
      )}
      {!loading && moves.length === 0 && (
        <p className="text-xs text-muted-foreground">No further moves from this stage.</p>
      )}
    </div>
  );
}
