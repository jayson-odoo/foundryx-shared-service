'use client';

import { notFound } from 'next/navigation';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useUserForm } from './use-user-form';

export interface UserFormViewProps {
  userId?: string;
  initialEditing: boolean;
}

/** Loads + renders a user form (create when userId is absent). */
export function UserFormView({ userId, initialEditing }: UserFormViewProps) {
  const { config, form, isLoading, notFound: recordNotFound } = useUserForm(userId, initialEditing);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  // AC-DLA-50 - an unknown user id renders the route's own not-found.tsx
  // (INSIDE app/(protected)/layout.tsx, chrome intact) via Next's real
  // notFound() boundary, not a hand-rolled inline message.
  if (recordNotFound || !config) {
    notFound();
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
