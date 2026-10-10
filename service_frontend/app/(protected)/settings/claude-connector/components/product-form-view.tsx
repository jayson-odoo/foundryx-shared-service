'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { CONNECTOR_PATH, useConnectorProductForm } from './use-connector-product-form';

export interface ProductFormViewProps {
  productKey?: string;
  initialEditing: boolean;
}

/** Loads + renders a connector product's settings form (create when no key). */
export function ProductFormView({ productKey, initialEditing }: ProductFormViewProps) {
  const { config, form, isLoading, notFound } = useConnectorProductForm(productKey, initialEditing);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Product not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={CONNECTOR_PATH}>Back to Claude connector</Link>
          </Button>
        </div>
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
