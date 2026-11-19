'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useFx } from '@/hooks/use-fx';
import { useContactForm } from './use-contact-form';
import { contactsListPath } from './paths';
import { FxContactRecord, FxNewContact } from './fx-contact-form-view';

export interface ContactFormViewProps {
  contactId?: string;
  workspaceId: string;
}

/**
 * Loads + renders a contact form (create when `contactId` is absent).
 * Foundryx UIUX switch on: the new-look record and new-contact pages
 * (`fx-contact-form-view.tsx`) from the same config. Off: unchanged.
 */
export function ContactFormView(props: ContactFormViewProps) {
  return useFx() ? (
    <FxContactFormView {...props} />
  ) : (
    <ContactFormViewLegacy {...props} />
  );
}

function FxContactFormView({ contactId, workspaceId }: ContactFormViewProps) {
  const { config, form, isLoading, notFound } = useContactForm(
    contactId,
    workspaceId,
  );

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-(--fx-ink-3)">
          <LoaderCircleIcon
            aria-label="Loading"
            className="size-6 animate-spin"
          />
        </div>
      </Container>
    );
  }

  if (notFound || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center text-(--fx-ink-2)">
          <p className="text-sm font-semibold">Contact not found.</p>
          <Link
            href={contactsListPath}
            className="text-sm font-semibold text-(--fx-link) transition-[translate] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-px"
          >
            Back to contacts
          </Link>
        </div>
      </Container>
    );
  }

  return contactId ? (
    <FxContactRecord config={config} />
  ) : (
    <FxNewContact config={config} form={form} />
  );
}

function ContactFormViewLegacy({ contactId, workspaceId }: ContactFormViewProps) {
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
