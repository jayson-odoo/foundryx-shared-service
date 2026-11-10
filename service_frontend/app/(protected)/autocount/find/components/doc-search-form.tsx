'use client';

import { useEffect, useMemo, useState } from 'react';
import { Search, TriangleAlert } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import type { AutocountCompany } from '@/types/autocount';
import type { DocLookupStartInput, DocLookupType } from '@/types/autocount-doc-lookup';

export interface DocSearchFormProps {
  companies: AutocountCompany[];
  types: DocLookupType[];
  companyId: string | null;
  onCompanyChange: (companyId: string) => void;
  busy: boolean;
  onSearch: (input: DocLookupStartInput) => void;
}

/** Longest registered prefix that starts the number (mirrors the backend's
 * `detect_doc_type`), else the first type. */
export function detectType(types: DocLookupType[], docNo: string): DocLookupType | null {
  const wanted = docNo.trim().toUpperCase();
  let best: DocLookupType | null = null;
  let bestLen = 0;
  for (const t of types) {
    for (const prefix of t.prefixes) {
      const p = prefix.toUpperCase();
      if (wanted.startsWith(p) && p.length > bestLen) {
        best = t;
        bestLen = p.length;
      }
    }
  }
  return best ?? types.find((t) => t.key === 'delivery_order') ?? types[0] ?? null;
}

export function DocSearchForm({
  companies,
  types,
  companyId,
  onCompanyChange,
  busy,
  onSearch,
}: DocSearchFormProps) {
  const [docNo, setDocNo] = useState('');
  const [docType, setDocType] = useState<string | null>(null);
  const [typeTouched, setTypeTouched] = useState(false);
  const [aroundDay, setAroundDay] = useState('');

  // The type follows the number until the user picks one themselves.
  useEffect(() => {
    if (typeTouched) return;
    setDocType(detectType(types, docNo)?.key ?? null);
  }, [docNo, types, typeTouched]);

  const companyOptions = useMemo(
    () => companies.map((c) => ({ label: c.name, value: c.id })),
    [companies],
  );
  const typeOptions = useMemo(() => types.map((t) => ({ label: t.label, value: t.key })), [types]);
  const selectedType = types.find((t) => t.key === docType) ?? null;
  const notConnected = Boolean(companyId && selectedType && selectedType.connected === false);
  const canSearch = Boolean(companyId && docNo.trim() && docType && !notConnected && !busy);

  const submit = () => {
    if (!canSearch || !companyId || !docType) return;
    onSearch({ companyId, docNo: docNo.trim(), docType, aroundDay: aroundDay || null });
  };

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-2 lg:grid-cols-[minmax(0,14rem)_minmax(0,12rem)_minmax(0,1fr)_minmax(0,11rem)_auto]">
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label>Company *</Label>
          <SearchSelect
            options={companyOptions}
            value={companyId}
            onChange={onCompanyChange}
            placeholder="Pick a company"
            ariaLabel="Company"
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label>Document type</Label>
          <SearchSelect
            options={typeOptions}
            value={docType}
            onChange={(value) => {
              setTypeTouched(true);
              setDocType(value);
            }}
            placeholder="Document type"
            ariaLabel="Document type"
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="ac-find-doc-no">Document number *</Label>
          <Input
            id="ac-find-doc-no"
            value={docNo}
            maxLength={64}
            autoComplete="off"
            onChange={(e) => setDocNo(e.target.value)}
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="ac-find-around">Around date</Label>
          <Input
            id="ac-find-around"
            type="date"
            value={aroundDay}
            onChange={(e) => setAroundDay(e.target.value)}
          />
        </div>
        <Button type="submit" variant="primary" disabled={!canSearch} className="w-full lg:w-auto">
          <Search className="size-4" />
          Find
        </Button>
      </div>
      {notConnected && selectedType && (
        <Alert variant="warning" appearance="light" data-testid="ac-find-not-connected">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>
            This company has no AutoCount connection for {selectedType.label.toLowerCase()}s yet.
          </AlertTitle>
        </Alert>
      )}
    </form>
  );
}
