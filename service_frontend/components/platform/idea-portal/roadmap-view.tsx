'use client';

import { useState } from 'react';
import { toast } from '@/lib/toast';
import { useIdeaPortal, usePortalProducts, usePortalRoadmap } from '@/hooks/use-idea-portal';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { RoadmapBoard } from './roadmap-board';
import { PortalLoading, PortalMessage } from './portal-states';

const ALL_PRODUCTS = '__all__';

export function RoadmapView() {
  const { paths, principal } = useIdeaPortal();
  const [mine, setMine] = useState(false);
  const [productId, setProductId] = useState<string | null>(null);
  const roadmap = usePortalRoadmap({ mine, productId });
  const products = usePortalProducts();
  const productOptions = [
    { value: ALL_PRODUCTS, label: 'All products' },
    ...(products.data ?? []).map((p) => ({ value: p.id, label: p.name })),
  ];

  const onVote = (id: string) => {
    roadmap.vote(id).catch(() => toast.error('Could not save your vote.'));
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <div role="heading" aria-level={1} className="font-heading text-xl font-semibold">Roadmap</div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {!principal.productId && (products.data?.length ?? 0) > 1 && (
            <SearchSelect
              className="w-48"
              ariaLabel="Product"
              options={productOptions}
              value={productId ?? ALL_PRODUCTS}
              onChange={(v) => setProductId(v === ALL_PRODUCTS ? null : v)}
            />
          )}
          {principal.kind === 'crm' && (
            <Button
              variant={mine ? 'primary' : 'outline'}
              size="sm"
              aria-pressed={mine}
              onClick={() => setMine((m) => !m)}
            >
              My ideas
            </Button>
          )}
        </div>
      </div>
      {roadmap.loading && !roadmap.data && <PortalLoading />}
      {roadmap.error && <PortalMessage text="The roadmap could not be loaded." />}
      {roadmap.data && <RoadmapBoard columns={roadmap.data.columns} ideaHref={paths.idea} onVote={onVote} />}
    </>
  );
}
