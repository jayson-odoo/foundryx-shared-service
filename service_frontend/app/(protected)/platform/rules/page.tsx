'use client';

import type { RuleSiteRow } from '@/types/rules';
import type { FxListConfig } from '@/components/platform/resource-list/types';
import { RulesPage } from '@/components/platform/rule-engine';

/** Foundryx UIUX switch only (slice W3-PLATFORM); ignored while off. */
const PLATFORM_RULES_FX: FxListConfig<RuleSiteRow> = {
  noun: 'rules',
  cardLines: [['context'], ['site'], ['summary']],
  phoneHidden: ['updated'],
};

/**
 * Operator surface of the Rule Engine (sprint-2/02 D12) - read-only
 * observability: every condition tree in the system + where it lives.
 */
export default function PlatformRulesPage() {
  return (
    <RulesPage
      description="Every rule configured across the platform - click a row to open it where it lives."
      statusEngineBase="/platform/status-engine"
      fx={PLATFORM_RULES_FX}
    />
  );
}
