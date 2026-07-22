'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useAgentForm } from './use-agent-form';
import { AI_AGENTS_PATH } from './paths';

export interface AgentFormViewProps {
  agentId?: string;
  initialEditing: boolean;
}

/** Loads + renders an agent form (create when agentId is absent). */
export function AgentFormView({ agentId, initialEditing }: AgentFormViewProps) {
  const { config, form, isLoading, notFound } = useAgentForm(agentId, initialEditing);

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
          <p className="text-sm font-medium">Agent not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={AI_AGENTS_PATH}>Back to agents</Link>
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
