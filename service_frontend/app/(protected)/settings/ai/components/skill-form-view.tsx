'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useSkillForm } from './use-skill-form';
import { AI_SKILLS_PATH } from './paths';

export interface SkillFormViewProps {
  skillId?: string;
  initialEditing: boolean;
}

/** Loads + renders a skill form (create when skillId is absent). */
export function SkillFormView({ skillId, initialEditing }: SkillFormViewProps) {
  const { config, form, isLoading, notFound } = useSkillForm(skillId, initialEditing);

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
          <p className="text-sm font-medium">Skill not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={AI_SKILLS_PATH}>Back to skills</Link>
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
