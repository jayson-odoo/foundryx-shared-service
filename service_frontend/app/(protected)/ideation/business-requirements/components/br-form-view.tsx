'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { ResourceForm } from '@/components/platform/resource-form';
import { useBrForm } from './use-br-form';
import { BR_PATH } from './paths';

export interface BrFormViewProps {
  brId: string;
  initialEditing: boolean;
  /** Deep-link a starting tab (e.g. `grill` — Promote-to-BR lands here). */
  initialTab?: string;
}

/** Loads + renders a Business Requirement detail form (tabbed ResourceForm). */
export function BrFormView({ brId, initialEditing, initialTab }: BrFormViewProps) {
  const { config, isLoading, notFound } = useBrForm(brId, initialEditing, initialTab);

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
          <p className="text-sm font-medium">Business requirement not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={BR_PATH}>Back to business requirements</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <ResourceForm config={config} />
    </Container>
  );
}
