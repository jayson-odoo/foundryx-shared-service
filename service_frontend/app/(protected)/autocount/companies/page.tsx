'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { AC_COMPANIES_READ } from '../components/autocount-meta';
import { useAutocountCompaniesListConfig } from './components/use-companies-list-config';

/** AutoCount companies (sprint-4/13 slice 1) - one row per connected company
 * database. Gated `autocount.companies.read`. */
export default function AutocountCompaniesPage() {
  const config = useAutocountCompaniesListConfig();

  return (
    <RequirePermission permission={AC_COMPANIES_READ}>
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text="AutoCount companies" />
              <ToolbarDescription>
                Connected AutoCount company databases.
              </ToolbarDescription>
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
