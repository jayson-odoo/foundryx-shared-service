'use client';

import { useEffect, useMemo, useState } from 'react';
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
              <Button variant="outline" size="sm" disabled={saving} onClick={() => void persist([])}>
                Use defaults
              </Button>
            )}
            <Button variant="primary" size="sm" disabled={saving || !dirty} onClick={onSave}>
              {saving && <Loader2 className="size-4 animate-spin" />}
              Save
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
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pe-2 font-medium">Key *</th>
                  <th className="py-2 pe-2 font-medium">Label</th>
                  <th className="py-2 pe-2 font-medium">Type *</th>
                  {canManage && <th className="w-10" />}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-b align-top last:border-b-0">
                    <td className="py-2 pe-2">
                      <Input
                        aria-label={`Key ${i + 1}`}
                        value={row.key}
                        maxLength={64}
                        disabled={!canManage}
                        aria-invalid={submitted && errors[i] ? true : undefined}
                        onChange={(e) => update(i, { key: e.target.value })}
                      />
                      {submitted && errors[i] && <p className="mt-1 text-xs text-destructive">{errors[i]}</p>}
                    </td>
                    <td className="py-2 pe-2">
                      <Input
                        aria-label={`Label ${i + 1}`}
                        value={row.label}
                        maxLength={200}
                        disabled={!canManage}
                        onChange={(e) => update(i, { label: e.target.value })}
                      />
                    </td>
                    <td className="py-2 pe-2">
                      <SearchSelect
                        ariaLabel={`Type ${i + 1}`}
                        options={TYPE_OPTIONS}
                        value={row.type}
                        disabled={!canManage}
                        onChange={(v) => update(i, { type: v as LeadFieldType })}
                      />
                    </td>
                    {canManage && (
                      <td className="py-2">
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
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
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
