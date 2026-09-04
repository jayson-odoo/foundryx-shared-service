'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  productService,
  type Product,
  type ProductKind,
} from '@/services/productService';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { ProductFormDialog } from './product-form-dialog';
import { useProductsListConfig } from './use-products-list-config';

/**
 * Products catalog (core master-data) on the shared ResourceList. Create + Edit
 * open the shared modal (CRUD-UX standard: modal by default). Kinds are fetched
 * once for the modal's kind picker (software appears only when Ideation is
 * installed for the tenant). A `version` bump remounts the list so its fetcher
 * re-pages over fresh data after a mutation.
 */
function ProductsView() {
  const [kinds, setKinds] = useState<ProductKind[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Product | undefined>(undefined);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    productService
      .listKinds()
      .then(setKinds)
      .catch(() => setKinds([]));
  }, []);

  const bump = useCallback(() => setVersion((v) => v + 1), []);

  const handlers = useMemo(
    () => ({
      onCreate: () => {
        setEditing(undefined);
        setDialogOpen(true);
      },
      onEdit: (product: Product) => {
        setEditing(product);
        setDialogOpen(true);
      },
      onDelete: async (product: Product) => {
        try {
          await productService.deleteProduct(product.id);
          toast.success('Product deleted.');
          bump();
        } catch (e) {
          toast.error(
            e instanceof Error ? e.message : 'Could not delete the product.',
          );
        }
      },
    }),
    [bump],
  );

  const config = useProductsListConfig(handlers);

  return (
    <Fragment>
      <ResourceList key={version} config={config} />
      {dialogOpen && (
        <ProductFormDialog
          product={editing}
          kinds={kinds}
          onClose={() => setDialogOpen(false)}
          onSaved={() => {
            toast.success(editing ? 'Product updated.' : 'Product created.');
            bump();
          }}
        />
      )}
    </Fragment>
  );
}

export default function ProductsPage() {
  return (
    <Fragment>
      <Container width="fluid">
        <ProductsView />
      </Container>
    </Fragment>
  );
}
