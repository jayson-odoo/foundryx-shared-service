'use client';

import { use } from 'react';
import { RequirePermission } from '@/components/common/require-permission';
import { AC_COMPANIES_MANAGE } from '../../../../../components/autocount-meta';
import { MappingEditorView } from './components/mapping-editor-view';

/**
 * The per-(company, entity) field-mapping editor (plan 15, AC-15-40..44). Gated
 * `autocount.companies.manage` - the same "configure the company" authority the
 * read/write endpoints reuse (no new permission, no grant sweep).
 */
export default function AutocountMappingPage({
  params,
}: {
  params: Promise<{ id: string; entityType: string }>;
}) {
  const { id, entityType } = use(params);

  return (
    <RequirePermission permission={AC_COMPANIES_MANAGE}>
      <MappingEditorView companyId={id} entityType={decodeURIComponent(entityType)} />
    </RequirePermission>
  );
}
