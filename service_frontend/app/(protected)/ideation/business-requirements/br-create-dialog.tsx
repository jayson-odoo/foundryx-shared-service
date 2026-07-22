'use client';

import { useState } from 'react';
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
import { SearchSelect } from '@/components/platform/search-select';
import type { Product } from '@/types/ideation';
import type { BusinessRequirementDetail } from '@/types/business-requirement';

export interface BrCreateDialogProps {
  products: Product[];
  onClose: () => void;
  onCreate: (input: {
    productId: string;
    title: string;
  }) => Promise<BusinessRequirementDetail>;
}

/**
 * Create a draft Business Requirement. Product + title only — the requirement
 * fields are filled on the detail's Details tab (or by the grill in S3), so a
 * draft anchor exists from turn zero (Bi-D15). Foolproof: product is required.
 */
export function BrCreateDialog({ products, onClose, onCreate }: BrCreateDialogProps) {
  const [productId, setProductId] = useState<string | null>(products[0]?.id ?? null);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = !!productId;

  const handleSave = async () => {
    if (!valid || !productId) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate({ productId, title: title.trim() });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the requirement.');
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New business requirement</DialogTitle>
          <DialogDescription>
            Creates a draft you can grill and fill out.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label>Product</Label>
            <SearchSelect
              value={productId}
              onChange={setProductId}
              options={products.map((p) => ({ value: p.id, label: p.name }))}
              placeholder="Select a product"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Title</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Order export to Excel"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!valid || saving}>
            {saving ? 'Creating…' : 'Create draft'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
