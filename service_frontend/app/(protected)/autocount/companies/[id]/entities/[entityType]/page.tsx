'use client';

import { use } from 'react';
import { useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { AC_COMPANIES_MANAGE, type AcTaskTab } from '../../../../components/autocount-meta';
import { TaskEditorView } from './components/task-editor-view';

const TABS: AcTaskTab[] = ['query', 'mapping', 'schedule', 'activate', 'runs'];

/** `?tab=` deep-links a tab (the entities list opens Mapping directly). */
function initialTab(value: string | null): AcTaskTab {
  return TABS.find((t) => t === value) ?? 'query';
}

/**
 * The per-(company, entity) Database-mode task editor (plan 22, AC-22-07).
 * Gated `autocount.companies.manage` - the same "configure the company"
 * authority the mapping editor reuses (no new permission, no grant sweep).
 */
export default function AutocountTaskPage({
  params,
}: {
  params: Promise<{ id: string; entityType: string }>;
}) {
  const { id, entityType } = use(params);
  const searchParams = useSearchParams();

  return (
    <RequirePermission permission={AC_COMPANIES_MANAGE}>
      <TaskEditorView
        companyId={id}
        entityType={decodeURIComponent(entityType)}
        initialTab={initialTab(searchParams.get('tab'))}
      />
    </RequirePermission>
  );
}
