'use client';

/** Client detail/form view — read + Edit-toggle fields, status shown + changed
 * from the form "…" (the graph's available next states). Mirrors profiles. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { ArrowRight, Briefcase, FileText, Info, LoaderCircleIcon } from 'lucide-react';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { ResourceList, type ResourceAction } from '@/components/platform/resource-list';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import { formatMoney } from '@/lib/money';
import type { Client, Lead, Quotation } from '@/types/ems';

const CLIENT_ENTITY = 'client';

interface DetailValues {
  name: string;
  registrationNo: string;
  contactPerson: string;
  contactEmail: string;
  contactPhone: string;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function ClientDetail({ clientId }: { clientId: string }) {
  const { labelPlural } = useTerminology();
  const engine = useStatusGraph(CLIENT_ENTITY);
  const form = useForm<DetailValues>({
    defaultValues: { name: '', registrationNo: '', contactPerson: '', contactEmail: '', contactPhone: '' },
  });

  const [record, setRecord] = useState<Client | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    return emsService.getClient(clientId).then((c) => {
      setRecord(c);
      form.reset({
        name: c.name ?? '',
        registrationNo: c.registrationNo ?? '',
        contactPerson: c.contactPerson ?? '',
        contactEmail: c.contactEmail ?? '',
        contactPhone: c.contactPhone ?? '',
      });
    });
  }, [clientId, form]);

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [load]);

  const values = form.watch();
  const statusLabel = useMemo(() => {
    const s = engine.graph?.statuses.find((x) => x.id === record?.statusId);
    return s?.label ?? '';
  }, [engine.graph, record?.statusId]);

  const config = useMemo<ResourceFormConfig<Client> | null>(() => {
    if (!record) return null;

    const moves = record.statusId
      ? (engine.graph?.transitions ?? []).filter((t) => t.fromStatusId === record.statusId)
      : [];
    const statusName = (id: string) =>
      engine.graph?.statuses.find((s) => s.id === id)?.label ?? id;
    const actions: ResourceAction<Client>[] = moves.map((t) => ({
      id: `move-${t.toStatusId}`,
      label: `${statusName(t.toStatusId)}`,
      icon: ArrowRight,
      surfaces: { row: false, form: true, bulk: false },
      permission: 'crm_clients.manage',
      run: async (_rows, runtime) => {
        try {
          await emsService.transitionClient(record.id, t.toStatusId);
          runtime.reload();
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not change the status.');
        }
      },
    }));

    return {
      breadcrumb: [{ label: labelPlural('client'), href: '/ems/clients' }, { label: record.name }],
      backHref: '/ems/clients',
      backLabel: labelPlural('client'),
      title: record.name,
      subtitle: record.contactEmail ?? undefined,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-5 py-2">
              <Row label="Status">
                {statusLabel ? (
                  <Badge variant="primary" appearance="light" size="sm">{statusLabel}</Badge>
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </Row>
              {(
                [
                  ['name', 'Name'],
                  ['registrationNo', 'Registration no.'],
                  ['contactPerson', 'Contact person'],
                  ['contactEmail', 'Contact email'],
                  ['contactPhone', 'Contact phone'],
                ] as [keyof DetailValues, string][]
              ).map(([key, lbl]) => (
                <Row key={key} label={lbl}>
                  {editing ? (
                    <Input
                      aria-label={lbl}
                      value={values[key]}
                      onChange={(e) => form.setValue(key, e.target.value, { shouldDirty: true })}
                    />
                  ) : (
                    <span className="text-sm">{values[key] || '—'}</span>
                  )}
                </Row>
              ))}
            </div>
          ),
        },
        {
          id: 'leads',
          label: labelPlural('lead'),
          icon: Briefcase,
          render: () => <RelatedLeads clientId={record.id} />,
        },
        {
          id: 'quotations',
          label: labelPlural('quotation'),
          icon: FileText,
          render: () => <RelatedQuotations clientId={record.id} />,
        },
      ],
      actions,
      actionRows: [record],
      onReload: () => load(),
      editable: true,
      editPermission: 'crm_clients.manage',
      isDirty: form.formState.isDirty,
      onSave: async () => {
        const updated = await emsService.updateClient(record.id, {
          name: values.name,
          registrationNo: values.registrationNo,
          contactPerson: values.contactPerson,
          contactEmail: values.contactEmail,
          contactPhone: values.contactPhone,
        });
        setRecord(updated);
        form.reset({
          name: updated.name ?? '',
          registrationNo: updated.registrationNo ?? '',
          contactPerson: updated.contactPerson ?? '',
          contactEmail: updated.contactEmail ?? '',
          contactPhone: updated.contactPhone ?? '',
        });
        return true;
      },
      onCancel: () =>
        form.reset({
          name: record.name ?? '',
          registrationNo: record.registrationNo ?? '',
          contactPerson: record.contactPerson ?? '',
          contactEmail: record.contactEmail ?? '',
          contactPhone: record.contactPhone ?? '',
        }),
    };
  }, [record, engine.graph, values, form, statusLabel, labelPlural, load]);

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
        <div className="py-24 text-center text-sm font-medium">Client not found.</div>
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

function RelatedLeads({ clientId }: { clientId: string }) {
  const config = useMemo(
    () =>
      embeddedListConfig<Lead>({
        viewKey: 'client_leads',
        getRowId: (r) => r.id,
        rowHref: (r) => `/ems/leads/${r.id}`,
        searchPlaceholder: 'Search leads…',
        fetcher: (q) => emsService.listLeadsQuery(q, clientId),
        columns: [
          { id: 'title', accessorKey: 'title', header: 'Title', cell: ({ row }) => <span className="font-medium">{row.original.title}</span> },
          { id: 'source', accessorKey: 'source', header: 'Source', cell: ({ row }) => <span className="text-muted-foreground">{row.original.source || '—'}</span> },
        ],
      }),
    [clientId],
  );
  return <ResourceList config={config} />;
}

function RelatedQuotations({ clientId }: { clientId: string }) {
  const config = useMemo(
    () =>
      embeddedListConfig<Quotation>({
        viewKey: 'client_quotations',
        getRowId: (r) => r.id,
        rowHref: (r) => `/ems/quotations/${r.id}`,
        searchPlaceholder: 'Search quotations…',
        fetcher: (q) => emsService.listQuotationsQuery(q, clientId),
        columns: [
          { id: 'revisionNumber', accessorKey: 'revisionNumber', header: 'Rev', cell: ({ row }) => <span className="font-medium">v{row.original.revisionNumber}</span> },
          { id: 'total', accessorKey: 'total', header: 'Total', cell: ({ row }) => <span>{formatMoney(row.original.total, row.original.currency)}</span> },
        ],
      }),
    [clientId],
  );
  return <ResourceList config={config} />;
}
