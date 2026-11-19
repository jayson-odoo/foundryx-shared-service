'use client';

import type { RuleSiteRow } from '@/types/rules';
import type { FxListConfig } from '@/components/platform/resource-list/types';
import { RulesPage } from '@/components/platform/rule-engine';

/** Foundryx UIUX switch only (slice W4-SETTINGS); ignored while off. */
const TENANT_RULES_FX: FxListConfig<RuleSiteRow> = {
  noun: 'rules',
  cardLines: [['context'], ['site'], ['summary']],
  phoneHidden: ['updated'],
};

/**
 * Tenant surface of the Rule Engine (sprint-2/02 D12) - same read-only
 * observability list, tenant-scoped by the backend.
 */
export default function TenantRulesPage() {
  return (
    <RulesPage
      description="Every rule configured in your workspace - click a row to open it where it lives."
      statusEngineBase="/settings/statuses"
      fx={TENANT_RULES_FX}
    />
  );
}
