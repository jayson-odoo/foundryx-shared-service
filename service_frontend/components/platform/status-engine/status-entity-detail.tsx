'use client';

/**
 * Entity detail (sprint-2/01 rework) - the ResourceForm shell over one
 * entity's status machine: Flow tab (graph canvas) + Statuses tab (reorder
 * list). The global Edit toggle gates every canvas/list mutation (read-only
 * by default, per the form design language). Drawer saves commit instantly,
 * so the form itself is never dirty - Save simply exits edit mode.
 */
import Link from 'next/link';
import { useMemo, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { CalendarClock, LoaderCircleIcon, ListOrdered, Workflow } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { ResourceAction } from '@/components/platform/resource-list';
import { useStatusEntities, useStatusGraph } from '@/hooks/use-status-engine';
import type { StatusEntity } from '@/types/status-engine';
import { EntityFlow, type LayoutController } from './entity-flow';
import { SimulateDateDialog } from './simulate-date-dialog';
import { StatusTable } from './status-table';

export interface StatusEntityDetailProps {
  entityType: string;
  /** The list surface this detail belongs to (operator vs tenant base path). */
  basePath: string;
  listLabel: string;
  initialEditing?: boolean;
}

export function StatusEntityDetail({
  entityType,
  basePath,
  listLabel,
  initialEditing = false,
}: StatusEntityDetailProps) {
  const { entities, loading: entitiesLoading } = useStatusEntities();
  const engine = useStatusGraph(entityType);
  // ResourceForm rides an RHF context; the engine has no plain fields - the
  // form exists for the shell chrome (breadcrumb/tabs/Edit toggle) only.
  const form = useForm();

  // Canvas layout is a DRAFT owned by the form's Save/Cancel (BL-064): Tidy/drag
  // mutate it, Save persists, Cancel discards (with the shell's unsaved-changes
  // dialog). EntityFlow exposes the save/discard handle + reports dirtiness.
  const layoutController = useRef<LayoutController | null>(null);
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [simulateOpen, setSimulateOpen] = useState(false);

  const entity = entities.find((e) => e.entityType === entityType);

  const config = useMemo<ResourceFormConfig<StatusEntity> | null>(() => {
    if (!entity) return null;
    return {
      breadcrumb: [{ label: listLabel, href: basePath }, { label: entity.label }],
      backHref: basePath,
      backLabel: listLabel,
      title: entity.label,
      subtitle:
        engine.graph?.source === 'tenant'
          ? 'Customized for this workspace'
          : 'Platform defaults - tenants inherit until they customize',
      tabs: [
        {
          id: 'flow',
          label: 'Flow',
          icon: Workflow,
          render: ({ editing }) => (
            <EntityFlow
              entityType={entityType}
              entityLabel={entity.label}
              engine={engine}
              editing={editing}
              onDirtyChange={setLayoutDirty}
              layoutController={layoutController}
            />
          ),
        },
        {
          id: 'statuses',
          label: 'Statuses',
          icon: ListOrdered,
          render: ({ editing }) => (
            <StatusTable
              statuses={engine.graph?.statuses ?? []}
              canManage={editing}
              entityLabel={entity.label}
              onReorder={engine.reorder}
              onRowClick={() => undefined}
            />
          ),
        },
      ],
      // "Simulate date" - only for time-capable entities (sprint-4/03 Slice 6):
      // fast-forward/backtrack "now" to test time-based auto edges.
      actions: (
        entity.hasTimeAutoEdges
          ? [
              {
                id: 'simulate-date',
                label: 'Simulate date',
                icon: CalendarClock,
                surfaces: { row: false, form: true, bulk: false },
                permission: 'statuses.manage',
                run: () => setSimulateOpen(true),
              } as ResourceAction<StatusEntity>,
            ]
          : []
      ),
      actionRows: [entity],
      editable: true,
      editPermission: 'statuses.manage',
      initialEditing,
      // Drawer/list mutations still commit instantly; the CANVAS LAYOUT is a
      // draft, so the form dirties on a Tidy/drag and Save/Cancel own it.
      isDirty: layoutDirty,
      onSave: () => {
        layoutController.current?.save();
        return true;
      },
      onCancel: () => layoutController.current?.discard(),
    };
  }, [entity, engine, entityType, basePath, listLabel, initialEditing, layoutDirty]);

  const statuses = engine.graph?.statuses ?? [];

  if (entitiesLoading || engine.loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (!config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Entity not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={basePath}>Back to {listLabel.toLowerCase()}</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
      {simulateOpen && entity && (
        <SimulateDateDialog
          entityType={entityType}
          entityLabel={entity.label}
          statuses={statuses}
          onClose={() => setSimulateOpen(false)}
        />
      )}
    </Container>
  );
}
