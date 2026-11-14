'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { KeyRound } from 'lucide-react';
import { toast } from '@/lib/toast';
import { ResourceList } from '@/components/platform/resource-list';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import type { BusinessRequirement } from '@/types/business-requirement';
import { useBusinessRequirements } from '@/hooks/use-business-requirements';
import { useCan } from '@/hooks/use-can';
import { useBrListConfig } from './use-br-list-config';
import { BrCreateDialog } from './br-create-dialog';
import { brFormHref } from './components/paths';
import { BuildKeysDialog } from './components/build-keys-dialog';
import { SEND_TO_BUILD_PERMISSION } from './components/use-br-build';

/** The Business Requirements repository grid (Resource shell). Create opens a
 * dialog → routes to the new draft's detail; row-click opens the detail form. */
export function BrView() {
  const router = useRouter();
  const {
    brs,
    products,
    loading,
    error,
    includeTest,
    setIncludeTest,
    create,
    remove,
  } = useBusinessRequirements();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [keysOpen, setKeysOpen] = useState(false);
  const { can } = useCan();

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

  const config = useBrListConfig(brs, handlers, includeTest);

  if (error && brs.length === 0) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (loading && brs.length === 0) {
    return <p className="text-sm text-muted-foreground">Loading business requirements…</p>;
  }

  return (
    <Fragment>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-3">
        {can(SEND_TO_BUILD_PERMISSION) && (
          <Button variant="outline" size="sm" onClick={() => setKeysOpen(true)}>
            <KeyRound />
            Build write-back keys
          </Button>
        )}
        <div className="flex items-center gap-1.5">
          <Switch
            id="br-include-test"
            checked={includeTest}
            onCheckedChange={setIncludeTest}
            data-testid="br-include-test"
          />
          <Label htmlFor="br-include-test" className="cursor-pointer text-sm">
            Show test requirements
          </Label>
        </div>
      </div>
      {keysOpen && <BuildKeysDialog open onOpenChange={setKeysOpen} />}
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
