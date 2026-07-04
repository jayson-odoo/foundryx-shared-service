'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useCan } from '@/hooks/use-can';
import { useFormDetail } from './use-form-detail';
import { FORMS_PATH } from './paths';

export interface FormDetailViewProps {
  formId?: string;
  initialEditing: boolean;
}

/** Loads + renders a form's detail (create when formId is absent). */
export function FormDetailView({ formId, initialEditing }: FormDetailViewProps) {
  const { can } = useCan();
  const { config, form, isLoading, notFound } = useFormDetail(
    formId,
    initialEditing,
    can('forms.manage'),
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
          <p className="text-sm font-medium">Form not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={FORMS_PATH}>Back to forms</Link>
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
