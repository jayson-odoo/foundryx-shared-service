'use client';

import { RulesPage } from '@/components/platform/rule-engine';

/**
 * Operator surface of the Rule Engine (sprint-2/02 D12) - read-only
 * observability: every condition tree in the system + where it lives.
 */
export default function PlatformRulesPage() {
  return (
    <RulesPage
      description="Every rule configured across the platform - click a row to open it where it lives."
      statusEngineBase="/platform/status-engine"
    />
  );
}
