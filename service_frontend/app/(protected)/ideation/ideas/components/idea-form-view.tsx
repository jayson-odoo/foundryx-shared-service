'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { useIdeaForm } from './use-idea-form';

export interface IdeaFormViewProps {
  ideaId?: string;
  initialEditing: boolean;
}

/** Loads + renders an idea form (create when ideaId is absent). */
export function IdeaFormView({ ideaId, initialEditing }: IdeaFormViewProps) {
  const { paths } = useIdeationRuntime();
  const { config, form, isLoading, notFound } = useIdeaForm(ideaId, initialEditing);

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
          <p className="text-sm font-medium">Idea not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={paths.listHref}>Back to ideas</Link>
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
