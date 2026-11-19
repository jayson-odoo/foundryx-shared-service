'use client';

/**
 * Shared Rules observability page (sprint-2/02 D12, deduped in code review) -
 * the operator and tenant surfaces render this with their own copy and
 * status-engine base path (used for row deep-links).
 */
import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import type { FxListConfig } from '@/components/platform/resource-list/types';
import type { RuleSiteRow } from '@/types/rules';
import { useRulesListConfig } from './use-rules-list-config';

export interface RulesPageProps {
  description: string;
  /** Where this surface edits status machines (deep-link base). */
  statusEngineBase: string;
  /** Foundryx UIUX switch choices for this surface (ignored while off). */
  fx?: FxListConfig<RuleSiteRow>;
}

export function RulesPage({ description, statusEngineBase, fx }: RulesPageProps) {
  const config = useRulesListConfig(statusEngineBase);

  return (
    <RequirePermission permission="rules.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={{ ...config, pageDescription: description, fx }} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
