'use client';

import { useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert, AlertContent, AlertIcon, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { useBrTemplateStatus } from '@/hooks/use-br-template-status';
import type { Product } from '@/types/ideation';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import { NO_TEMPLATE_MESSAGE, isBrTemplateUnavailable } from './components/br-template-error';

export interface BrCreateDialogProps {
  products: Product[];
  onClose: () => void;
  onCreate: (input: {
    productId: string;
    title: string;
  }) => Promise<BusinessRequirementDetail>;
}

/**
 * Create a draft Business Requirement. Product + title only - the requirement
 * fields are filled on the detail's Details tab (or by the grill in S3), so a
 * draft anchor exists from turn zero (Bi-D15). Foolproof: product is required.
 */
export function BrCreateDialog({ products, onClose, onCreate }: BrCreateDialogProps) {
  const [productId, setProductId] = useState<string | null>(products[0]?.id ?? null);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { active: hookActive, loading: templateStatusLoading } = useBrTemplateStatus();
  // A 422 on submit forces the Alert even if the hook read `active: true`
  // moments earlier (issue #90 W2, AC-90-210) - never let a race let Create
  // stay enabled after the backend just refused.
  const [templateUnavailable, setTemplateUnavailable] = useState(false);
  const templateActive = !templateUnavailable && (templateStatusLoading || hookActive);

  const valid = !!productId && templateActive;

  const handleSave = async () => {
    if (!valid || !productId) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate({ productId, title: title.trim() });
      onClose();
    } catch (e) {
      if (isBrTemplateUnavailable(e)) {
        setTemplateUnavailable(true);
        setSaving(false);
        return;
      }
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
          {!templateActive && (
            <Alert variant="warning" appearance="light">
              <AlertIcon>
                <TriangleAlert />
              </AlertIcon>
              <AlertContent>
                <AlertTitle>No active requirement template</AlertTitle>
                <AlertDescription>{NO_TEMPLATE_MESSAGE}</AlertDescription>
              </AlertContent>
            </Alert>
          )}
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
