'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useConnectionForm } from './use-connection-form';
import { integrationsListPath } from './paths';

export interface ConnectionFormViewProps {
  connectionId?: string;
  initialEditing: boolean;
  /** Preselect this provider when creating (module settings deep-links). */
  initialProvider?: string;
}

/** Loads + renders a connection form (create when connectionId is absent). */
export function ConnectionFormView({
  connectionId,
  initialEditing,
  initialProvider,
}: ConnectionFormViewProps) {
  const { config, form, isLoading, notFound } = useConnectionForm(
    connectionId,
    initialEditing,
    initialProvider,
  );

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
          <p className="text-sm font-medium">Connection not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={integrationsListPath}>Back to integrations</Link>
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
