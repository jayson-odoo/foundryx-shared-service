'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useCan } from '@/hooks/use-can';
import { useWorkflowForm } from './use-workflow-form';
import { WORKFLOWS_PATH } from './paths';

export interface WorkflowFormViewProps {
  workflowId?: string;
  initialEditing: boolean;
  debugRunId?: string;
}

/** Loads + renders a workflow form (create when workflowId is absent). */
export function WorkflowFormView({ workflowId, initialEditing, debugRunId }: WorkflowFormViewProps) {
  const { can } = useCan();
  const { config, form, isLoading, notFound } = useWorkflowForm(
    workflowId,
    initialEditing,
    can('workflows.manage'),
    debugRunId,
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
          <p className="text-sm font-medium">Workflow not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={WORKFLOWS_PATH}>Back to workflows</Link>
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
