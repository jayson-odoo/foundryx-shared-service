'use client';

import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { useImportsListConfig } from './use-imports-list-config';

/**
 * Import history (sprint-3/09 D9; AC-DLA-56 T7 - moved onto the Resource
 * shell, it IS a server-paginated list). Gated forms.read? No - any
 * authenticated user reaching here; the engine's own jobs are scoped
 * server-side (own jobs unless imports.read_all). Title via Terminology
 * (PageHeader resolves it from the menu's termKey entry).
 */
export default function ImportsHistoryPage() {
  const config = useImportsListConfig();

  return (
    <Container width="fluid">
      <ResourceList config={config} />
    </Container>
  );
}
