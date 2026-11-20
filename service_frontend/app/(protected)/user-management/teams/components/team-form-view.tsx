'use client';

import { notFound } from 'next/navigation';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useTeamForm } from './use-team-form';

export interface TeamFormViewProps {
  teamId?: string;
  initialEditing: boolean;
}

/** Loads + renders a team form (create when teamId is absent). Users clone. */
export function TeamFormView({ teamId, initialEditing }: TeamFormViewProps) {
  const {
    config,
    form,
    isLoading,
    notFound: recordNotFound,
    loadError,
  } = useTeamForm(teamId, initialEditing);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (loadError) {
    throw loadError;
  }

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
