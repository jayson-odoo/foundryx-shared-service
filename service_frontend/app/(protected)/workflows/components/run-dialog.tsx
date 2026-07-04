'use client';

/** Manual-run input collector (plan sprint-2/08 D12). Shows the trigger's
 * declared inputs; empty list = the caller runs immediately without opening. */
import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { WorkflowManualInput } from '@/types/workflows';

export interface RunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  inputs: WorkflowManualInput[];
  busy: boolean;
  onRun: (values: Record<string, string | number | boolean>) => void;
}

export function RunDialog({ open, onOpenChange, inputs, busy, onRun }: RunDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) setValues(Object.fromEntries(inputs.map((i) => [i.key, ''])));
  }, [open, inputs]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Run workflow</DialogTitle>
          <DialogDescription>Provide the inputs this run needs.</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          {inputs.map((input) => (
            <div key={input.key} className="flex flex-col gap-1.5">
              <Label className="text-xs font-medium">{input.label || input.key}</Label>
              <Input
                value={values[input.key] ?? ''}
                aria-label={input.label || input.key}
                data-testid={`run-input-${input.key}`}
                onChange={(e) => setValues((v) => ({ ...v, [input.key]: e.target.value }))}
              />
            </div>
          ))}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" disabled={busy} data-testid="run-dialog-submit" onClick={() => onRun(values)}>
            Run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
