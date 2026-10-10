'use client';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AccessTab } from './components/access-tab';
import { ProductsTab } from './components/products-tab';
import { useConnectorGrantListConfig } from './components/use-connector-grant-list-config';

export default function ClaudeConnectorPage() {
  const config = useConnectorGrantListConfig();

  return (
    <RequirePermission permission="connector.read">
      <Container width="fluid">
        <PageHeader
          title="Claude connector"
          crumbs={[{ label: 'Settings' }, { label: 'Claude connector' }]}
        />
        <Tabs defaultValue="grants" className="gap-4">
          <TabsList variant="line">
            <TabsTrigger value="grants">Grants</TabsTrigger>
            <TabsTrigger value="products">Products</TabsTrigger>
            <TabsTrigger value="access">Access</TabsTrigger>
          </TabsList>
          <TabsContent value="grants">
            <ResourceList config={config} hideHeader />
          </TabsContent>
          <TabsContent value="products">
            <ProductsTab />
          </TabsContent>
          {/* kept mounted so unsaved Access edits survive a tab switch */}
          <TabsContent value="access" forceMount className="data-[state=inactive]:hidden">
            <AccessTab />
          </TabsContent>
        </Tabs>
      </Container>
    </RequirePermission>
  );
}
