'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { TriageBoard } from './triage-board';

/**
 * Idea triage board (plan Phase A) - the operator page. Renders the shared
 * {@link TriageBoard} Kanban in operator mode (ideation runtime default). The
 * same board renders chrome-less in the host iframe via the embed runtime
 * (WS-C1). Drag across columns → status change; within a column → reorder.
 */
export default function IdeationBoardPage() {
  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>
              Drag across columns to change status, or within a column to reorder priority.
            </ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <TriageBoard />
      </Container>
    </Fragment>
  );
}
