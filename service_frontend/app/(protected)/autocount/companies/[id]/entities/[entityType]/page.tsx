'use client';

import { use } from 'react';
import { RequirePermission } from '@/components/common/require-permission';
import { AC_COMPANIES_MANAGE } from '../../../../components/autocount-meta';
import { TaskEditorView } from './components/task-editor-view';

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

  return (
    <RequirePermission permission={AC_COMPANIES_MANAGE}>
      <TaskEditorView companyId={id} entityType={decodeURIComponent(entityType)} />
    </RequirePermission>
  );
}
