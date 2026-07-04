'use client';

/** Dedicated product create page (sprint-4/08) — replaces the create popup, like
 * users/roles. Full-page form → POST → open the new product. */
import { Fragment, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import {
  Toolbar,
  ToolbarActions,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { SearchSelect } from '@/components/platform/search-select';
import { emsService } from '@/services/ems-service';
import { CURRENCY_OPTIONS } from '@/lib/money';
import type { ProductCategory, ProductKind } from '@/types/ems';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

function NewProductForm() {
  const router = useRouter();
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [kinds, setKinds] = useState<ProductKind[]>([]);
  const [name, setName] = useState('');
  const [kind, setKind] = useState('service');
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [sku, setSku] = useState('');
  const [price, setPrice] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [tax, setTax] = useState('');
  const [uom, setUom] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    emsService.listCategories().then(setCategories).catch(() => setCategories([]));
    emsService.productKinds().then((ks) => {
      setKinds(ks);
      if (ks.length && !ks.some((k) => k.key === 'service')) setKind(ks[0].key);
    }).catch(() => setKinds([]));
    emsService.getTenantSettings().then((s) => setCurrency(s.defaultCurrency)).catch(() => undefined);
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const p = await emsService.createProduct({
        name,
        kind,
        categoryId: categoryId || undefined,
        sku: sku || undefined,
        defaultPrice: price ? Number(price) : undefined,
        tax: tax ? Number(tax) : undefined,
        currency: currency || undefined,
        uom: uom || undefined,
        isActive,
      });
      toast.success('Product created.');
      router.push(`/ems/products/${p.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create the product.');
      setBusy(false);
    }
  };

  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle text="New product" />
            <ToolbarDescription>Add a catalog product or service.</ToolbarDescription>
          </ToolbarHeading>
          <ToolbarActions>
            <Button variant="outline" onClick={() => router.push('/ems/products')} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void save()} disabled={!name.trim() || !kind || busy}>
              {busy ? 'Creating…' : 'Create'}
            </Button>
          </ToolbarActions>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <Card>
          <CardContent className="flex flex-col gap-5 py-5">
            <Row label="Name *">
              <Input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            </Row>
            <Row label="Kind *">
              <SearchSelect value={kind} onChange={(v) => setKind(v || 'service')} options={kinds.map((k) => ({ value: k.key, label: k.label }))} />
            </Row>
            <Row label="Category">
              <SearchSelect value={categoryId} onChange={(v) => setCategoryId(v || null)} options={categories.map((c) => ({ value: c.id, label: c.name }))} placeholder="Uncategorized" />
            </Row>
            <Row label="SKU">
              <Input aria-label="SKU" value={sku} onChange={(e) => setSku(e.target.value)} />
            </Row>
            <Row label="Default price">
              <div className="flex gap-2">
                <div className="w-28 shrink-0">
                  <SearchSelect value={currency} onChange={(v) => setCurrency(v || 'USD')} options={CURRENCY_OPTIONS} />
                </div>
                <Input aria-label="Default price" type="number" className="flex-1" value={price} onChange={(e) => setPrice(e.target.value)} />
              </div>
            </Row>
            <Row label="Tax">
              <Input aria-label="Tax" type="number" value={tax} onChange={(e) => setTax(e.target.value)} />
            </Row>
            <Row label="Unit of measure">
              <Input aria-label="Unit of measure" value={uom} onChange={(e) => setUom(e.target.value)} />
            </Row>
            <Row label="Active">
              <Switch checked={isActive} onCheckedChange={setIsActive} />
            </Row>
          </CardContent>
        </Card>
      </Container>
    </Fragment>
  );
}

export default function NewProductPage() {
  return (
    <RequirePermission permission="products.create">
      <NewProductForm />
    </RequirePermission>
  );
}
