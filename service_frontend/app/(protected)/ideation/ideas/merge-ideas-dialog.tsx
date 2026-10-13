'use client';

import { useMemo, useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { cn } from '@/lib/utils';
import {
  MERGE_ROWS,
  canSubmitMerge,
  combineMergeValue,
  defaultMergeChoices,
  ideaLabel,
  mergeFieldsPayload,
  toggleMergeChoice,
  type MergeRow,
  type MergeValue,
} from '@/lib/idea-merge';
import type { Idea, MergeFieldChoices } from '@/types/ideation';

export interface MergeIdeasDialogProps {
  /** The ideas to merge, one column each, in this order (plan 20, AC-20-16). */
  ideas: Idea[];
  /** The idea kept by default - the page the merge was started from. Falls
   * back to the first column. */
  initialKeptId?: string;
  onClose: () => void;
  onMerge: (survivorId: string, fields: MergeFieldChoices) => Promise<void>;
}

const LABEL_CELL = 'sticky left-0 z-(--z-sticky-content) w-24 shrink-0 bg-background pr-2 text-sm font-medium sm:w-40';
const IDEA_CELL = 'min-w-48 flex-1 sm:min-w-56';

function MergeValueView({ value }: { value: MergeValue }) {
  if (value === null) return <span className="text-muted-foreground">-</span>;
  if (Array.isArray(value)) {
    return (
      <ul className="list-disc space-y-0.5 pl-4">
        {value.map((item, i) => (
          <li key={`${i}-${item}`}>{item}</li>
        ))}
      </ul>
    );
  }
  return <span className="whitespace-pre-wrap break-words">{value}</span>;
}

/**
 * Field-level merge (plan 20, AC-20-16): one column per idea, one row per
 * field, a tick in every cell that has a value. Several ticks in a row combine
 * those values (Result preview). The radio in each column header picks the idea
 * that is kept. Votes, comments and attachments always carry over. Not a
 * destructive confirm - the merge is reversible via Unmerge.
 */
export function MergeIdeasDialog({ ideas, initialKeptId, onClose, onMerge }: MergeIdeasDialogProps) {
  const columnOrder = useMemo(() => ideas.map((i) => i.id), [ideas]);
  const [keptId, setKeptId] = useState<string>(
    initialKeptId && columnOrder.includes(initialKeptId) ? initialKeptId : columnOrder[0],
  );
  const [choices, setChoices] = useState<MergeFieldChoices>(() =>
    defaultMergeChoices(ideas, keptId),
  );
  // Until the user changes a tick, the defaults follow the kept idea.
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = canSubmitMerge(choices, ideas);

  const handleMerge = async () => {
    if (!ready) return;
    setSaving(true);
    setError(null);
    try {
      await onMerge(keptId, mergeFieldsPayload(choices));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not merge these ideas.');
      setSaving(false);
    }
  };

  const toggle = (row: MergeRow, ideaId: string) => {
    setTouched(true);
    setChoices((prev) => toggleMergeChoice(prev, row.key, ideaId, columnOrder));
  };

  const changeKept = (id: string) => {
    setKeptId(id);
    if (!touched) setChoices(defaultMergeChoices(ideas, id));
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>Merge ideas</DialogTitle>
          <DialogDescription className="sr-only">Merge ideas</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="overflow-x-auto">
            <div className="flex min-w-max flex-col divide-y divide-border sm:min-w-full">
              <RadioGroup
                value={keptId}
                onValueChange={changeKept}
                aria-label="Idea to keep"
                className="flex gap-3 pb-2"
              >
                <div className={LABEL_CELL} />
                {ideas.map((idea) => (
                  <label
                    key={idea.id}
                    className={cn(IDEA_CELL, 'flex cursor-pointer items-center gap-2 text-sm')}
                  >
                    <RadioGroupItem value={idea.id} aria-label={`Keep ${ideaLabel(idea)}`} />
                    <span className="font-medium">{ideaLabel(idea)}</span>
                    {idea.id === keptId && (
                      <Badge variant="primary" appearance="light" size="sm">
                        Kept
                      </Badge>
                    )}
                  </label>
                ))}
              </RadioGroup>

              {MERGE_ROWS.map((row) => {
                const chosen = choices[row.key] ?? [];
                const combined =
                  chosen.length > 1
                    ? combineMergeValue(
                        row,
                        chosen.map((id) => ideas.find((i) => i.id === id)).filter((i): i is Idea => !!i),
                      )
                    : null;
                return (
                  <div key={row.key} className="space-y-2 py-3" data-testid={`merge-row-${row.key}`}>
                    <div className="flex gap-3">
                      <div className={LABEL_CELL}>{row.label}</div>
                      {ideas.map((idea) => {
                        const value = row.read(idea);
                        const checked = chosen.includes(idea.id);
                        if (value === null) {
                          return (
                            <div
                              key={idea.id}
                              className={cn(IDEA_CELL, 'rounded-md border border-border p-2 text-sm')}
                            >
                              <MergeValueView value={null} />
                            </div>
                          );
                        }
                        return (
                          <label
                            key={idea.id}
                            className={cn(
                              IDEA_CELL,
                              'flex cursor-pointer gap-2 rounded-md border p-2 text-sm transition-colors',
                              checked ? 'border-primary bg-primary/5' : 'border-border text-muted-foreground',
                            )}
                          >
                            <Checkbox
                              size="sm"
                              checked={checked}
                              onCheckedChange={() => toggle(row, idea.id)}
                              aria-label={`Use ${ideaLabel(idea)} ${row.label}`}
                              className="mt-0.5"
                            />
                            <MergeValueView value={value} />
                          </label>
                        );
                      })}
                    </div>
                    {combined !== null && (
                      <div className="flex gap-3">
                        <div className={LABEL_CELL} />
                        <div className="flex-1 rounded-md border border-dashed border-border bg-muted/50 p-2 text-xs">
                          <p className="mb-1 font-medium text-muted-foreground">Result</p>
                          <MergeValueView value={combined} />
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

              <div className="flex gap-3 py-3">
                <div className={LABEL_CELL}>Carried over</div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="success" appearance="light">
                    Votes
                  </Badge>
                  <Badge variant="success" appearance="light">
                    Comments
                  </Badge>
                  <Badge variant="success" appearance="light">
                    Attachments
                  </Badge>
                </div>
              </div>
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleMerge} disabled={!ready || saving}>
            Merge
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
