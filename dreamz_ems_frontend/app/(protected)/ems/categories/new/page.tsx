'use client';

/** Dedicated category create page (sprint-4/08). Optional ?parentId= pre-selects
 * the parent (used by "Add sub-category"). */
import { Fragment, Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';
import {
  Toolbar,
  ToolbarActions,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { emsService } from '@/services/ems-service';
import type { ProductCategory } from '@/types/ems';

const ROOT_SENTINEL = '__root__';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

function NewCategoryForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [cats, setCats] = useState<ProductCategory[]>([]);
  const [name, setName] = useState('');
  const [parentId, setParentId] = useState<string>(params.get('parentId') || ROOT_SENTINEL);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    emsService.listCategories().then(setCats).catch(() => setCats([]));
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      await emsService.createCategory({
        name,
        parentId: parentId === ROOT_SENTINEL ? null : parentId,
      });
      toast.success('Category created.');
      router.push('/ems/categories');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create the category.');
      setBusy(false);
    }
  };

  const parentOptions = [
    { value: ROOT_SENTINEL, label: 'Top level (no parent)' },
    ...cats.map((c) => ({ value: c.id, label: c.name })),
  ];

  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle text="New category" />
            <ToolbarDescription>Add a product category.</ToolbarDescription>
          </ToolbarHeading>
          <ToolbarActions>
            <Button variant="outline" onClick={() => router.push('/ems/categories')} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void save()} disabled={!name.trim() || busy}>
              {busy ? 'Creating…' : 'Create'}
            </Button>
          </ToolbarActions>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <Card>
          <CardContent className="flex flex-col gap-5 py-5">
            <Row label="Name *">
              <Input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            </Row>
            <Row label="Parent">
              <SearchSelect value={parentId} onChange={(v) => setParentId(v || ROOT_SENTINEL)} options={parentOptions} />
            </Row>
          </CardContent>
        </Card>
      </Container>
    </Fragment>
  );
}

export default function NewCategoryPage() {
  return (
    <RequirePermission permission="product_categories.manage">
      <Suspense fallback={null}>
        <NewCategoryForm />
      </Suspense>
    </RequirePermission>
  );
}
