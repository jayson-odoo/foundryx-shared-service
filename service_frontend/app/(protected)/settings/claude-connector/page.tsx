'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ProductsTab } from './components/products-tab';
import { useConnectorGrantListConfig } from './components/use-connector-grant-list-config';

export default function ClaudeConnectorPage() {
  const config = useConnectorGrantListConfig();

  return (
    <RequirePermission permission="connector.read">
      <div className="mx-auto w-full px-4 lg:px-6">
        <Tabs defaultValue="grants" className="gap-4">
          <TabsList variant="line">
            <TabsTrigger value="grants">Grants</TabsTrigger>
            <TabsTrigger value="products">Products</TabsTrigger>
          </TabsList>
          <TabsContent value="grants">
            <ResourceList config={config} />
          </TabsContent>
          <TabsContent value="products">
            <ProductsTab />
          </TabsContent>
        </Tabs>
      </div>
    </RequirePermission>
  );
}
