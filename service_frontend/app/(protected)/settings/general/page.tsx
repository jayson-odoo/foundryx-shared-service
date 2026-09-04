'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { CURRENCY_OPTIONS } from '@/lib/money';
import { useCan } from '@/hooks/use-can';
import { emsService } from '@/services/ems-service';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { SearchSelect } from '@/components/platform/search-select';

const CURRENCIES = CURRENCY_OPTIONS;

/** Tenant general settings (sprint-4/08) - default currency + price decimal
 * places for the catalog and quotations. A product/quotation can override the
 * currency; this is the fallback. */
function GeneralSettingsForm() {
  const { can } = useCan();
  const canManage = can('settings.update');
  const [currency, setCurrency] = useState<string>('USD');
  const [decimals, setDecimals] = useState<string>('2');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    emsService
      .getTenantSettings()
      .then((s) => {
        setCurrency(s.defaultCurrency);
        setDecimals(String(s.priceDecimals));
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    const dp = Number(decimals);
    if (!Number.isInteger(dp) || dp < 0 || dp > 6) {
      toast.error('Decimal places must be a whole number between 0 and 6.');
      return;
    }
    setSaving(true);
    try {
      const s = await emsService.setTenantSettings({
        defaultCurrency: currency,
        priceDecimals: dp,
      });
      setCurrency(s.defaultCurrency);
      setDecimals(String(s.priceDecimals));
      toast.success('Settings saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Default currency</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label>Currency</Label>
          <SearchSelect
            value={currency}
            onChange={(v) => setCurrency(v || 'USD')}
            options={CURRENCIES}
          />
          <p className="text-xs text-muted-foreground">
            Used for catalog prices and quotations unless a product or quotation
            sets its own.
          </p>
        </div>
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label htmlFor="price-decimals">Price decimal places</Label>
          <Input
            id="price-decimals"
            type="number"
            min={0}
            max={6}
            value={decimals}
            disabled={loading || !canManage}
            onChange={(e) => setDecimals(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            How many decimals to show on money amounts (0-6).
          </p>
        </div>
        {canManage && (
          <div>
            <Button onClick={() => void save()} disabled={saving || loading}>
              Save
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function GeneralSettingsPage() {
  return (
    <RequirePermission permission="settings.read">
      <Container width="fluid">
        <PageHeader description="General workspace settings." />
        <GeneralSettingsForm />
      </Container>
    </RequirePermission>
  );
}
