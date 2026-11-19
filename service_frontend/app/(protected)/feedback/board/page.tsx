'use client';

import { Container } from '@/components/common/container';
import { useFx } from '@/hooks/use-fx';
import { PageHeader } from '@/components/platform/page-header';
import { TriageBoard } from './triage-board';

/**
 * Idea triage board (plan Phase A) - the operator page. Renders the shared
 * {@link TriageBoard} Kanban in operator mode (ideation runtime default). The
 * same board renders chrome-less in the host iframe via the embed runtime
 * (WS-C1). Drag across columns → status change; within a column → reorder.
 */
export default function IdeationBoardPage() {
  const fx = useFx();
  return (
    <Container width="fluid">
      <PageHeader
        description={
          fx ? undefined : 'Drag across columns to change status, or within a column to reorder priority.'
        }
      />
      <TriageBoard />
    </Container>
  );
}
