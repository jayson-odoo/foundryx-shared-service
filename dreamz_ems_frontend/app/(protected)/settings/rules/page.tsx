'use client';

import { RulesPage } from '@/components/platform/rule-engine';

/**
 * Tenant surface of the Rule Engine (sprint-2/02 D12) — same read-only
 * observability list, tenant-scoped by the backend.
 */
export default function TenantRulesPage() {
  return (
    <RulesPage
      description="Every rule configured in your workspace — click a row to open it where it lives."
      statusEngineBase="/settings/statuses"
    />
  );
}
