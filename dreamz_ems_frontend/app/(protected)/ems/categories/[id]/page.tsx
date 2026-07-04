'use client';

/** Category detail/edit page (sprint-4/08) — name, parent (cycle-guarded), sort,
 * delete. The form view the tree links into. */
import { Fragment, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useCan } from '@/hooks/use-can';
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

/** Ids of `id` + all its descendants — barred as parent targets (no cycles). */
function descendants(id: string, rows: ProductCategory[]): Set<string> {
  const out = new Set<string>([id]);
  let added = true;
  while (added) {
    added = false;
    for (const r of rows) {
      if (r.parentId && out.has(r.parentId) && !out.has(r.id)) {
        out.add(r.id);
        added = true;
      }
    }
  }
  return out;
}

function CategoryDetail({ id }: { id: string }) {
  const router = useRouter();
  const { can } = useCan();
  const manage = can('product_categories.manage');
  const [cats, setCats] = useState<ProductCategory[]>([]);
  const [name, setName] = useState('');
  const [parentId, setParentId] = useState<string>(ROOT_SENTINEL);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    Promise.all([emsService.getCategory(id), emsService.listCategories()])
      .then(([c, all]) => {
        setName(c.name);
        setParentId(c.parentId ?? ROOT_SENTINEL);
        setCats(all);
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Could not load.'))
      .finally(() => setLoading(false));
  }, [id]);

  const parentOptions = useMemo(() => {
    const barred = descendants(id, cats);
    return [
      { value: ROOT_SENTINEL, label: 'Top level (no parent)' },
      ...cats.filter((c) => !barred.has(c.id)).map((c) => ({ value: c.id, label: c.name })),
    ];
  }, [id, cats]);

  const save = async () => {
    setBusy(true);
    try {
      await emsService.updateCategory(id, {
        name,
        parentId: parentId === ROOT_SENTINEL ? null : parentId,
      });
      toast.success('Saved.');
      router.push('/ems/categories');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  if (loading) {
    return <Container width="fluid"><div className="py-24 text-center text-sm text-muted-foreground">Loading…</div></Container>;
  }

  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle text={name} />
            <ToolbarDescription>Category</ToolbarDescription>
          </ToolbarHeading>
          <ToolbarActions>
            {manage && (
              <Button variant="outline" className="text-destructive" onClick={() => setDeleting(true)} disabled={busy}>
                Delete
              </Button>
            )}
            <Button variant="outline" onClick={() => router.push('/ems/categories')} disabled={busy}>
              Cancel
            </Button>
            {manage && (
              <Button onClick={() => void save()} disabled={!name.trim() || busy}>
                {busy ? 'Saving…' : 'Save'}
              </Button>
            )}
          </ToolbarActions>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <Card>
          <CardContent className="flex flex-col gap-5 py-5">
            <Row label="Name *">
              <Input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} disabled={!manage} />
            </Row>
            <Row label="Parent">
              <SearchSelect value={parentId} onChange={(v) => setParentId(v || ROOT_SENTINEL)} options={parentOptions} />
            </Row>
          </CardContent>
        </Card>
      </Container>
      {deleting && (
        <AlertDialog open onOpenChange={(o) => !o && setDeleting(false)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete “{name}”?</AlertDialogTitle>
              <AlertDialogDescription>A category with sub-categories or products can’t be deleted.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={async () => {
                  try {
                    await emsService.deleteCategory(id);
                    toast.success('Category deleted.');
                    router.push('/ems/categories');
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : 'Could not delete.');
                    setDeleting(false);
                  }
                }}
              >
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </Fragment>
  );
}

export default function CategoryDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="product_categories.read">
      <CategoryDetail id={params.id} />
    </RequirePermission>
  );
}
