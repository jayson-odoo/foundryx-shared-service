'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from '@/lib/toast';
import { ResourceList } from '@/components/platform/resource-list';
import type { BusinessRequirement } from '@/types/business-requirement';
import { useBusinessRequirements } from '@/hooks/use-business-requirements';
import { useBrListConfig } from './use-br-list-config';
import { BrCreateDialog } from './br-create-dialog';
import { brFormHref } from './components/paths';

/** The Business Requirements repository grid (Resource shell). Create opens a
 * dialog → routes to the new draft's detail; row-click opens the detail form. */
export function BrView() {
  const router = useRouter();
  const { brs, products, loading, error, create, remove } = useBusinessRequirements();
  const [dialogOpen, setDialogOpen] = useState(false);

  // Remount the ResourceList on data change so the client fetcher re-pages.
  const [version, setVersion] = useState(0);
  const prev = useRef(brs);
  useEffect(() => {
    if (prev.current !== brs) {
      prev.current = brs;
      setVersion((v) => v + 1);
    }
  }, [brs]);

  const handlers = useMemo(
    () => ({
      onCreate: () => setDialogOpen(true),
      onDelete: async (br: BusinessRequirement) => {
        try {
          await remove(br.id);
          toast.success('Business requirement deleted.');
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not delete.');
        }
      },
    }),
    [remove],
  );

  const config = useBrListConfig(brs, handlers);

  if (error && brs.length === 0) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (loading && brs.length === 0) {
    return <p className="text-sm text-muted-foreground">Loading business requirements…</p>;
  }

  return (
    <Fragment>
      <ResourceList key={version} config={config} />
      {dialogOpen && (
        <BrCreateDialog
          products={products}
          onClose={() => setDialogOpen(false)}
          onCreate={async (input) => {
            const created = await create(input);
            toast.success('Draft requirement created.');
            router.push(brFormHref(created.id, { edit: true }));
            return created;
          }}
        />
      )}
    </Fragment>
  );
}
