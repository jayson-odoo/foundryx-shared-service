'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { emsService } from '@/services/ems-service';
import type { Product, ProductCategory } from '@/types/ems';
import { useProductsListConfig } from './use-products-list-config';

export default function ProductsPage() {
  const router = useRouter();
  const [categories, setCategories] = useState<ProductCategory[]>([]);

  useEffect(() => {
    emsService.listCategories().then(setCategories).catch(() => setCategories([]));
  }, []);

  const onCreate = useCallback(() => router.push('/ems/products/new'), [router]);
  const onEdit = useCallback((row: Product) => router.push(`/ems/products/${row.id}`), [router]);
  const categoryName = useCallback(
    (id: string | null) => (id ? categories.find((c) => c.id === id)?.name ?? '—' : '—'),
    [categories],
  );

  const config = useProductsListConfig(useMemo(() => ({ onCreate, onEdit, categoryName }), [onCreate, onEdit, categoryName]));

  return (
    <RequirePermission permission="products.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Your product catalog.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
