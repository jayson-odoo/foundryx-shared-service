'use client';

/**
 * Shared Rules observability page (sprint-2/02 D12, deduped in code review) -
 * the operator and tenant surfaces render this with their own copy and
 * status-engine base path (used for row deep-links).
 */
import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useRulesListConfig } from './use-rules-list-config';

export interface RulesPageProps {
  description: string;
  /** Where this surface edits status machines (deep-link base). */
  statusEngineBase: string;
}

export function RulesPage({ description, statusEngineBase }: RulesPageProps) {
  const config = useRulesListConfig(statusEngineBase);

  return (
    <RequirePermission permission="rules.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>{description}</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
