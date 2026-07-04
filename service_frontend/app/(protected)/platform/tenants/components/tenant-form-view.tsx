'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useTenantForm } from './use-tenant-form';
import { tenantsListPath } from './paths';

export interface TenantFormViewProps {
  tenantId?: string;
  initialEditing: boolean;
}

/** Loads + renders a tenant form (provision when tenantId is absent). */
export function TenantFormView({ tenantId, initialEditing }: TenantFormViewProps) {
  const { config, form, isLoading, notFound } = useTenantForm(tenantId, initialEditing);

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
          <p className="text-sm font-medium">Tenant not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={tenantsListPath}>Back to tenants</Link>
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
