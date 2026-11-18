'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowDown, ArrowUp, Loader2, MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Alert, AlertIcon, AlertTitle, AlertToolbar } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardHeading, CardTitle, CardToolbar } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { deferredToast, dismissDeferredToast } from '@/components/platform/resource-actions/deferred-toast';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { leadCaptureErrorMessage, type LoadState } from '@/hooks/use-lead-capture';
import {
  LEAD_FIELD_TYPE_LABELS,
  MAX_LEAD_FIELDS,
  validateLeadFields,
} from '@/lib/lead-field-map';
import type { LeadField, LeadFieldList, LeadFieldType } from '@/types/lead-capture';

export interface LeadFieldsCardProps {
  state: LoadState<LeadFieldList>;
  saving: boolean;
  save: (fields: LeadField[]) => Promise<LeadFieldList>;
  canManage: boolean;
  onSaved: () => void;
}

const TYPE_OPTIONS = (Object.keys(LEAD_FIELD_TYPE_LABELS) as LeadFieldType[]).map((value) => ({
  value,
  label: LEAD_FIELD_TYPE_LABELS[value],
}));

const same = (a: LeadField[], b: LeadField[]) => JSON.stringify(a) === JSON.stringify(b);

/**
 * The product's own lead fields (the map targets) as an editable line grid.
 * Save replaces the list; "Use defaults" clears it back to Name, Phone, Email,
 * Lead notes. Row moves/removal live in each line's menu.
 */
export function LeadFieldsCard({ state, saving, save, canManage, onSaved }: LeadFieldsCardProps) {
  const [rows, setRows] = useState<LeadField[]>([]);
  const [submitted, setSubmitted] = useState(false);
  const toastIdRef = useRef<string | number | null>(null);
  const settle = () => {
    if (toastIdRef.current !== null) dismissDeferredToast(toastIdRef.current);
    toastIdRef.current = null;
  };
  // "Use defaults" replaces the list: a grace-window action (countdown +
  // Cancel), committed server-side by `lead_capture_fields.reset`.
  const reset = useDeferredAction({
    onCommitted: () => {
      settle();
      toast.success('Lead fields set to the defaults.');
      onSaved();
    },
    onFailed: (error) => {
      settle();
      toast.error(error || 'Could not set the default fields.');
    },
    onCancelledElsewhere: settle,
  });

  const startReset = async () => {
    try {
      const { commitAt, windowSeconds } = await reset.start('lead_capture_fields.reset', {
        entityType: 'lead_capture_fields',
        entityId: 'fields',
      });
      toastIdRef.current = deferredToast({
        id: 'pending-action-lead-capture-fields',
        verb: 'Setting default fields',
        commitAt,
        windowSeconds,
        onCancel: () => {
          void reset.cancel();
          settle();
        },
      });
    } catch (err) {
      toast.error(leadCaptureErrorMessage(err, 'Could not set the default fields.'));
    }
  };
  const loaded = state.data?.data;

  useEffect(() => {
    if (loaded) setRows(loaded.map((f) => ({ ...f })));
  }, [loaded]);

  const errors = useMemo(() => validateLeadFields(rows), [rows]);
  const dirty = loaded ? !same(rows, loaded) : false;

  const update = (index: number, patch: Partial<LeadField>) =>
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  const move = (index: number, delta: number) =>
    setRows((prev) => {
      const next = [...prev];
      const [row] = next.splice(index, 1);
      next.splice(index + delta, 0, row);
      return next;
    });
  const removeRow = (index: number) => setRows((prev) => prev.filter((_, i) => i !== index));
  const addRow = () => setRows((prev) => [...prev, { key: '', label: '', type: 'text' }]);

  const persist = async (next: LeadField[]) => {
    try {
      await save(next);
      toast.success('Lead fields saved.');
      setSubmitted(false);
      onSaved();
    } catch (err) {
      toast.error(leadCaptureErrorMessage(err, 'Could not save the lead fields. Please try again.'));
    }
  };

  const onSave = () => {
    setSubmitted(true);
    if (Object.keys(errors).length > 0) return;
    void persist(rows.map((r) => ({ ...r, key: r.key.trim(), label: r.label.trim() || r.key.trim() })));
  };

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Lead fields</CardTitle>
        </CardHeading>
        {canManage && state.data && (
          <CardToolbar>
            {!state.data.isDefault && (
              <Button variant="outline" size="sm" disabled={saving || reset.state.status === 'pending'} onClick={() => void startReset()}>
                Use defaults
              </Button>
            )}
            <Button variant="outline" size="sm" disabled={saving || !dirty} onClick={onSave}>
              {saving && <Loader2 className="size-4 animate-spin" />}
              Save fields
            </Button>
          </CardToolbar>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {state.loading && !state.data && <Loader2 className="size-5 animate-spin text-muted-foreground" />}
        {state.error && !state.data && (
          <Alert variant="destructive">
            <AlertIcon>
              <AlertCircle />
            </AlertIcon>
            <AlertTitle>{state.error}</AlertTitle>
            <AlertToolbar>
              <Button variant="outline" size="sm" onClick={state.reload}>
                Try again
              </Button>
            </AlertToolbar>
          </Alert>
        )}
        {state.data && (
          <div>
            <div className="flex flex-col text-sm" role="list" aria-label="Lead fields">
              <div className="hidden grid-cols-[1fr_1fr_1fr_2.5rem] gap-2 border-b py-2 text-xs font-medium text-muted-foreground sm:grid">
                <span>Key *</span>
                <span>Label</span>
                <span>Type *</span>
                <span />
              </div>
              {rows.map((row, i) => (
                <div
                  key={i}
                  role="listitem"
                  className="grid grid-cols-[1fr_2.5rem] items-start gap-2 border-b py-2 last:border-b-0 sm:grid-cols-[1fr_1fr_1fr_2.5rem]"
                >
                  {/* Phone width: Key, Label and Type stack beside the line menu. */}
                  <div className="flex min-w-0 flex-col gap-2 sm:contents">
                  <div>
                    <Input
                      aria-label={`Key ${i + 1}`}
                      placeholder="Key *"
                      value={row.key}
                      maxLength={64}
                      disabled={!canManage}
                      aria-invalid={submitted && errors[i] ? true : undefined}
                      onChange={(e) => update(i, { key: e.target.value })}
                    />
                    {submitted && errors[i] && <p className="mt-1 text-xs text-destructive">{errors[i]}</p>}
                  </div>
                  <Input
                    aria-label={`Label ${i + 1}`}
                    placeholder="Label"
                    value={row.label}
                    maxLength={200}
                    disabled={!canManage}
                    onChange={(e) => update(i, { label: e.target.value })}
                  />
                  <SearchSelect
                    ariaLabel={`Type ${i + 1}`}
                    options={TYPE_OPTIONS}
                    value={row.type}
                    disabled={!canManage}
                    onChange={(v) => update(i, { type: v as LeadFieldType })}
                  />
                  </div>
                  <div>
                    {canManage && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" mode="icon" size="sm" aria-label={`Line ${i + 1} actions`}>
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem disabled={i === 0} onSelect={() => move(i, -1)}>
                            <ArrowUp className="size-4" /> Move up
                          </DropdownMenuItem>
                          <DropdownMenuItem disabled={i === rows.length - 1} onSelect={() => move(i, 1)}>
                            <ArrowDown className="size-4" /> Move down
                          </DropdownMenuItem>
                          <DropdownMenuItem variant="destructive" onSelect={() => removeRow(i)}>
                            <Trash2 className="size-4" /> Remove
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {canManage && rows.length < MAX_LEAD_FIELDS && (
              <Button variant="outline" size="sm" className="mt-3" onClick={addRow}>
                <Plus className="size-4" /> Add field
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
