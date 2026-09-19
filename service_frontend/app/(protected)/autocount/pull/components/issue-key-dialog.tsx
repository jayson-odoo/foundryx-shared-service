'use client';

import { useEffect, useState } from 'react';
import { Check, Copy, KeyRound } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/platform/multi-select';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { useIssuePullKey } from '@/hooks/use-autocount-pull';
import type { AutocountCompany } from '@/types/autocount';

export interface IssueKeyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  companies: AutocountCompany[];
  onIssued: () => void;
}

/**
 * Issue-key dialog (AC-10-38) - name + company `MultiSelect`, then the
 * plaintext key shown exactly ONCE with a copy control (AC-10-28). Closing
 * clears every field, including the plaintext - it is never persisted or
 * re-derivable afterwards.
 */
export function IssueKeyDialog({ open, onOpenChange, companies, onIssued }: IssueKeyDialogProps) {
  const { issuing, error, fieldErrors, issue, reset } = useIssuePullKey();
  const [name, setName] = useState('');
  const [companyIds, setCompanyIds] = useState<string[]>([]);
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const { isCopied, copyToClipboard } = useCopyToClipboard();

  useEffect(() => {
    if (!open) {
      setName('');
      setCompanyIds([]);
      setPlaintext(null);
      reset();
    }
  }, [open, reset]);

  const companyOptions = companies.map((c) => ({ label: c.name, value: c.id }));

  async function submit() {
    const result = await issue({ name: name.trim(), companyIds });
    if (result) {
      setPlaintext(result.plaintext);
      onIssued();
    }
  }

  const revealed = plaintext !== null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{revealed ? 'Key issued' : 'Issue key'}</DialogTitle>
        </DialogHeader>

        {!revealed ? (
          <>
            <DialogBody className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pull-key-name">Name</Label>
                <Input
                  id="pull-key-name"
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  aria-invalid={Boolean(fieldErrors.name)}
                />
                {fieldErrors.name && <p className="text-xs text-destructive">{fieldErrors.name}</p>}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Companies</Label>
                <MultiSelect
                  options={companyOptions}
                  value={companyIds}
                  onChange={setCompanyIds}
                  placeholder="Pick companies"
                />
                {fieldErrors.companyIds && (
                  <p className="text-xs text-destructive">{fieldErrors.companyIds}</p>
                )}
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={issuing}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => void submit()}
                disabled={issuing || !name.trim() || companyIds.length === 0}
              >
                <KeyRound className="size-4" />
                Issue key
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogBody className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <Input
                  readOnly
                  value={plaintext ?? ''}
                  className="font-mono text-sm"
                  aria-label="Plaintext key"
                  onFocus={(e) => e.currentTarget.select()}
                />
                <Button
                  variant="outline"
                  mode="icon"
                  onClick={() => copyToClipboard(plaintext ?? '')}
                  aria-label="Copy key"
                >
                  {isCopied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                </Button>
              </div>
              <p className="text-sm font-medium text-destructive">
                Copy this key now - it will not be shown again.
              </p>
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
