'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useUserForm } from './use-user-form';
import { usersListPath } from './paths';

export interface UserFormViewProps {
  userId?: string;
  initialEditing: boolean;
}

/** Loads + renders a user form (create when userId is absent). */
export function UserFormView({ userId, initialEditing }: UserFormViewProps) {
  const { config, form, isLoading, notFound } = useUserForm(userId, initialEditing);

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
          <p className="text-sm font-medium">User not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={usersListPath}>Back to users</Link>
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
