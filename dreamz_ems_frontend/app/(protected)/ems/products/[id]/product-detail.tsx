'use client';

/** Product detail/form — read + Edit-toggle fields (name/kind/category/sku/
 * price/tax/uom/active). `kind` drives behavior; `is_active` is a plain flag. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Info, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Form } from '@/components/ui/form';
import { SearchSelect } from '@/components/platform/search-select';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import { CURRENCY_OPTIONS, formatMoney } from '@/lib/money';
import type { Product, ProductCategory, ProductKind } from '@/types/ems';

interface DetailValues {
  name: string;
  kind: string;
  categoryId: string;
  sku: string;
  defaultPrice: string;
  tax: string;
  currency: string;
  uom: string;
  isActive: boolean;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function ProductDetail({ productId }: { productId: string }) {
  const { labelPlural } = useTerminology();
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [kinds, setKinds] = useState<ProductKind[]>([]);
  const form = useForm<DetailValues>({
    defaultValues: { name: '', kind: 'service', categoryId: '', sku: '', defaultPrice: '', tax: '', currency: '', uom: '', isActive: true },
  });
  const [record, setRecord] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);

  const reset = useCallback(
    (p: Product) =>
      form.reset({
        name: p.name ?? '',
        kind: p.kind,
        categoryId: p.categoryId ?? '',
        sku: p.sku ?? '',
        defaultPrice: p.defaultPrice == null ? '' : String(p.defaultPrice),
        tax: p.tax == null ? '' : String(p.tax),
        currency: p.currency ?? '',
        uom: p.uom ?? '',
        isActive: p.isActive,
      }),
    [form],
  );

  const load = useCallback(
    () => emsService.getProduct(productId).then((p) => { setRecord(p); reset(p); }),
    [productId, reset],
  );

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    emsService.listCategories().then((rows) => active && setCategories(rows));
    emsService.productKinds().then((ks) => active && setKinds(ks));
    return () => { active = false; };
  }, [load]);

  const values = form.watch();

  const config = useMemo<ResourceFormConfig<Product> | null>(() => {
    if (!record) return null;
    return {
      breadcrumb: [{ label: labelPlural('product'), href: '/ems/products' }, { label: record.name }],
      backHref: '/ems/products',
      backLabel: labelPlural('product'),
      title: record.name,
      subtitle: record.sku ?? undefined,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-5 py-2">
              <Row label="Name">
                {editing ? (
                  <Input aria-label="Name" value={values.name} onChange={(e) => form.setValue('name', e.target.value, { shouldDirty: true })} />
                ) : (
                  <span className="text-sm">{values.name || '—'}</span>
                )}
              </Row>
              <Row label="Kind">
                {editing ? (
                  <SearchSelect value={values.kind} onChange={(v) => form.setValue('kind', v || 'service', { shouldDirty: true })} options={kinds.map((k) => ({ value: k.key, label: k.label }))} />
                ) : (
                  <Badge variant="secondary" appearance="light" size="sm">
                    {record.kindLabel || kinds.find((k) => k.key === values.kind)?.label || values.kind}
                  </Badge>
                )}
              </Row>
              <Row label="Category">
                {editing ? (
                  <SearchSelect value={values.categoryId || null} onChange={(v) => form.setValue('categoryId', v || '', { shouldDirty: true })} options={categories.map((c) => ({ value: c.id, label: c.name }))} placeholder="Uncategorized" />
                ) : (
                  <span className="text-sm">{categories.find((c) => c.id === values.categoryId)?.name || '—'}</span>
                )}
              </Row>
              <Row label="SKU">
                {editing ? (
                  <Input aria-label="SKU" value={values.sku} onChange={(e) => form.setValue('sku', e.target.value, { shouldDirty: true })} />
                ) : (
                  <span className="text-sm">{values.sku || '—'}</span>
                )}
              </Row>
              <Row label="Default price">
                {editing ? (
                  <div className="flex gap-2">
                    <div className="w-28 shrink-0">
                      <SearchSelect value={values.currency || null} onChange={(v) => form.setValue('currency', v || '', { shouldDirty: true })} options={CURRENCY_OPTIONS} placeholder="Currency" />
                    </div>
                    <Input aria-label="Default price" type="number" className="flex-1" value={values.defaultPrice} onChange={(e) => form.setValue('defaultPrice', e.target.value, { shouldDirty: true })} />
                  </div>
                ) : (
                  <span className="text-sm">
                    {values.defaultPrice === '' ? '—' : formatMoney(Number(values.defaultPrice), values.currency || null)}
                  </span>
                )}
              </Row>
              {(
                [
                  ['tax', 'Tax'],
                  ['uom', 'Unit of measure'],
                ] as [keyof DetailValues, string][]
              ).map(([key, lbl]) => (
                <Row key={key} label={lbl}>
                  {editing ? (
                    <Input aria-label={lbl} value={values[key] as string} onChange={(e) => form.setValue(key, e.target.value, { shouldDirty: true })} />
                  ) : (
                    <span className="text-sm">{(values[key] as string) || '—'}</span>
                  )}
                </Row>
              ))}
              <Row label="Active">
                {editing ? (
                  <Switch checked={values.isActive} onCheckedChange={(c) => form.setValue('isActive', c, { shouldDirty: true })} />
                ) : values.isActive ? (
                  <Badge variant="success" appearance="light" size="sm">Active</Badge>
                ) : (
                  <Badge variant="secondary" appearance="light" size="sm">Inactive</Badge>
                )}
              </Row>
            </div>
          ),
        },
      ],
      actions: [],
      actionRows: [record],
      onReload: () => load(),
      editable: true,
      editPermission: 'products.update',
      isDirty: form.formState.isDirty,
      onSave: async () => {
        const updated = await emsService.updateProduct(record.id, {
          name: values.name,
          kind: values.kind,
          categoryId: values.categoryId || null,
          sku: values.sku,
          defaultPrice: values.defaultPrice === '' ? null : Number(values.defaultPrice),
          tax: values.tax === '' ? null : Number(values.tax),
          currency: values.currency || null,
          uom: values.uom,
          isActive: values.isActive,
        });
        setRecord(updated);
        reset(updated);
        return true;
      },
      onCancel: () => reset(record),
    };
  }, [record, values, form, categories, kinds, labelPlural, load, reset]);

  if (loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }
  if (!config) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">Product not found.</div>
      </Container>
    );
  }
  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
