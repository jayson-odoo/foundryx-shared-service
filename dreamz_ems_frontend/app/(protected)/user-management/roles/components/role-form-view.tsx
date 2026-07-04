'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useRoleForm } from './use-role-form';
import { rolesListPath } from './paths';

export interface RoleFormViewProps {
  roleId?: string;
  initialEditing: boolean;
}

/** Loads + renders a role form (create when roleId is absent). */
export function RoleFormView({ roleId, initialEditing }: RoleFormViewProps) {
  const { config, form, isLoading, notFound } = useRoleForm(roleId, initialEditing);

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
          <p className="text-sm font-medium">Role not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={rolesListPath}>Back to roles</Link>
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
