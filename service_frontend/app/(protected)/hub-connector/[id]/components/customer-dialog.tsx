'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from '@/lib/toast';
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
import { hubConnectorErrorMessage, useHubOptions } from '@/hooks/use-hub-connector';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { HubCustomer, Option } from '@/types/hub-connector';

export interface CustomerDialogProps {
  hubId: string;
  open: boolean;
  /** The row being edited; null = a new customer. */
  customer: HubCustomer | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}

const toItems = (o: Option) => ({ label: `${o.name} (${o.code})`, value: o.code });

/** Merge the saved selections in, so a code the picker no longer lists still shows its name. */
function withSelected(options: Option[], selected: Option[]): Option[] {
  const have = new Set(options.map((o) => o.code));
  return [...options, ...selected.filter((o) => !have.has(o.code))];
}

/** Add or edit one customer's policy: which locations and brands it sees. */
export function CustomerDialog({ hubId, open, customer, onOpenChange, onSaved }: CustomerDialogProps) {
  const editing = customer !== null;
  const locationOptions = useHubOptions('locations', open);
  const brandOptions = useHubOptions('brands', open);
  const [customerCode, setCustomerCode] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [locationCodes, setLocationCodes] = useState<string[]>([]);
  const [brandCodes, setBrandCodes] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCustomerCode(customer?.customerCode ?? '');
    setCustomerName(customer?.customerName ?? '');
    setLocationCodes(customer?.locationCodes ?? []);
    setBrandCodes(customer?.brandCodes ?? []);
  }, [open, customer]);

  const locationItems = useMemo(
    () => withSelected(locationOptions, customer?.locations ?? []).map(toItems),
    [locationOptions, customer],
  );
  const brandItems = useMemo(
    () => withSelected(brandOptions, customer?.brands ?? []).map(toItems),
    [brandOptions, customer],
  );

  const valid = customerName.trim() !== '' && (editing || customerCode.trim() !== '');

  const save = async () => {
    if (saving || !valid) return;
    setSaving(true);
    try {
      if (customer) {
        await hubConnectorService.updateCustomer(hubId, customer.id, {
          customerName: customerName.trim(),
          locationCodes,
          brandCodes,
        });
      } else {
        await hubConnectorService.createCustomer(hubId, {
          customerCode: customerCode.trim(),
          customerName: customerName.trim(),
          locationCodes,
          brandCodes,
        });
      }
      onSaved();
      onOpenChange(false);
    } catch (err) {
      toast.error(hubConnectorErrorMessage(err, 'Could not save the customer. Please try again.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{editing ? customer.customerName : 'Add customer'}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="hub-customer-code">Customer code{editing ? '' : ' *'}</Label>
            <Input
              id="hub-customer-code"
              maxLength={100}
              value={customerCode}
              readOnly={editing}
              disabled={editing}
              onChange={(e) => setCustomerCode(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="hub-customer-name">Customer name *</Label>
            <Input
              id="hub-customer-name"
              maxLength={200}
              value={customerName}
              onChange={(e) => setCustomerName(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Locations</Label>
            <MultiSelect
              ariaLabel="Locations"
              options={locationItems}
              value={locationCodes}
              onChange={setLocationCodes}
              placeholder="Select locations"
              searchPlaceholder="Search locations…"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Brands</Label>
            <MultiSelect
              ariaLabel="Brands"
              options={brandItems}
              value={brandCodes}
              onChange={setBrandCodes}
              placeholder="Select brands"
              searchPlaceholder="Search brands…"
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={saving || !valid}>
            {saving && <Loader2 className="size-4 animate-spin" />}
            {editing ? 'Save' : 'Add'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
