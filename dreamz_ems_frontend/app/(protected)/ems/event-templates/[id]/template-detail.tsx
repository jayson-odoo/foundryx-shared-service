'use client';

/** Event Template detail — Details + the eligibility-flow editor (AC-11-12).
 * The flow IS the scoped status canvas (`EntityFlow`, scope = template_id),
 * materialized at template creation and tenant-owned from birth, gated by the
 * form's global Edit toggle. Reuses the status-engine canvas verbatim — no new
 * editor. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { LoaderCircleIcon, Info, Tags, UserCog, Workflow } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { EntityFlow, type LayoutController } from '@/components/platform/status-engine';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { ProjectTemplate, TemplateChild } from '@/types/ems';
import { ChildListEditor } from './child-list-editor';

/** The participant eligibility machine is scoped to its owning template. */
const PARTICIPANT_ENTITY = 'project_participant';

interface DetailValues {
  name: string;
  description: string;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function TemplateDetail({ templateId }: { templateId: string }) {
  const { label, labelPlural } = useTerminology();
  const singular = label('project_template');
  const plural = labelPlural('project_template');
  const engine = useStatusGraph(PARTICIPANT_ENTITY, templateId);
  const form = useForm<DetailValues>({ defaultValues: { name: '', description: '' } });

  const [record, setRecord] = useState<ProjectTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [roles, setRoles] = useState<TemplateChild[]>([]);
  const [segments, setSegments] = useState<TemplateChild[]>([]);
  const layoutController = useRef<LayoutController | null>(null);
  const [layoutDirty, setLayoutDirty] = useState(false);

  const refreshRoles = () => emsService.listRoles(templateId).then(setRoles).catch(() => {});
  const refreshSegments = () => emsService.listSegments(templateId).then(setSegments).catch(() => {});

  useEffect(() => {
    let active = true;
    Promise.all([
      emsService.getTemplate(templateId),
      emsService.listRoles(templateId),
      emsService.listSegments(templateId),
    ])
      .then(([t, r, s]) => {
        if (!active) return;
        setRecord(t);
        setRoles(r);
        setSegments(s);
        form.reset({ name: t.name, description: t.description ?? '' });
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [templateId, form]);

  const values = form.watch();

  const config = useMemo<ResourceFormConfig<ProjectTemplate> | null>(() => {
    if (!record) return null;
    return {
      breadcrumb: [{ label: plural, href: '/ems/event-templates' }, { label: record.name }],
      backHref: '/ems/event-templates',
      backLabel: plural,
      title: record.name,
      subtitle: `Eligibility flow for ${singular.toLowerCase()}s built on this template`,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-5 py-2">
              <Row label="Name">
                {editing ? (
                  <Input
                    aria-label="Template name"
                    value={values.name}
                    onChange={(e) => form.setValue('name', e.target.value, { shouldDirty: true })}
                  />
                ) : (
                  <span className="text-sm font-medium">{values.name || '—'}</span>
                )}
              </Row>
              <Row label="Description">
                {editing ? (
                  <Textarea
                    aria-label="Template description"
                    rows={3}
                    value={values.description}
                    onChange={(e) =>
                      form.setValue('description', e.target.value, { shouldDirty: true })
                    }
                  />
                ) : (
                  <span className="text-sm text-muted-foreground">{values.description || '—'}</span>
                )}
              </Row>
            </div>
          ),
        },
        {
          id: 'roles',
          label: 'Roles',
          icon: UserCog,
          render: ({ editing }) => (
            <ChildListEditor
              items={roles}
              editing={editing}
              emptyLabel="No roles yet."
              addPlaceholder="Role name (e.g. Attendee, Volunteer)"
              onAdd={async (name) => {
                await emsService.addRole(record.id, name);
                await refreshRoles();
              }}
              onDelete={async (id) => {
                await emsService.deleteRole(record.id, id);
                await refreshRoles();
              }}
            />
          ),
        },
        {
          id: 'segments',
          label: 'Segments',
          icon: Tags,
          render: ({ editing }) => (
            <ChildListEditor
              items={segments}
              editing={editing}
              emptyLabel="No segments yet."
              addPlaceholder="Segment name (e.g. by distance)"
              onAdd={async (name) => {
                await emsService.addSegment(record.id, name);
                await refreshSegments();
              }}
              onDelete={async (id) => {
                await emsService.deleteSegment(record.id, id);
                await refreshSegments();
              }}
            />
          ),
        },
        {
          id: 'flow',
          label: 'Eligibility flow',
          icon: Workflow,
          render: ({ editing }) => (
            <EntityFlow
              entityType={PARTICIPANT_ENTITY}
              entityLabel={`${record.name} eligibility`}
              engine={engine}
              editing={editing}
              onDirtyChange={setLayoutDirty}
              layoutController={layoutController}
            />
          ),
        },
      ],
      actions: [],
      actionRows: [record],
      editable: true,
      editPermission: 'project_templates.manage',
      isDirty: form.formState.isDirty || layoutDirty,
      onSave: async () => {
        if (form.formState.isDirty) {
          const updated = await emsService.updateTemplate(record.id, {
            name: values.name,
            description: values.description,
          });
          setRecord(updated);
          form.reset({ name: updated.name, description: updated.description ?? '' });
        }
        layoutController.current?.save();
        return true;
      },
      onCancel: () => {
        form.reset({ name: record.name, description: record.description ?? '' });
        layoutController.current?.discard();
      },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record, engine, values, form, singular, plural, layoutDirty, roles, segments]);

  if (loading || engine.loading) {
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
        <div className="py-24 text-center text-sm font-medium">Template not found.</div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
