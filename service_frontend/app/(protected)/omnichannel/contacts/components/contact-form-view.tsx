'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useContactForm } from './use-contact-form';
import { contactsListPath } from './paths';

export interface ContactFormViewProps {
  contactId?: string;
  workspaceId: string;
}

/** Loads + renders a contact form (create when `contactId` is absent). */
export function ContactFormView({ contactId, workspaceId }: ContactFormViewProps) {
  const { config, form, isLoading, notFound } = useContactForm(contactId, workspaceId);

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
          <p className="text-sm font-medium">Contact not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={contactsListPath}>Back to contacts</Link>
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
