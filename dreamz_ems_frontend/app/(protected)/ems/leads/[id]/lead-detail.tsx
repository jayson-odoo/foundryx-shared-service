'use client';

/** Lead detail/form view — read + Edit-toggle fields (incl. client link), status
 * shown + changed from the form "…", and a graph-driven "Create event" (Won →
 * spawn + link a Project). Mirrors profiles/clients with the convert addition. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useForm } from 'react-hook-form';
import { ArrowRight, CalendarPlus, Info, LoaderCircleIcon } from 'lucide-react';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { SearchSelect } from '@/components/platform/search-select';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { ResourceList, type ResourceAction } from '@/components/platform/resource-list';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { Client, Lead, LeadEvent } from '@/types/ems';

const LEAD_ENTITY = 'lead';

interface DetailValues {
  title: string;
  source: string;
  contactName: string;
  contactEmail: string;
  contactPhone: string;
  notes: string;
  clientId: string;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function LeadDetail({ leadId }: { leadId: string }) {
  const { labelPlural } = useTerminology();
  const engine = useStatusGraph(LEAD_ENTITY);
  const form = useForm<DetailValues>({
    defaultValues: { title: '', source: '', contactName: '', contactEmail: '', contactPhone: '', notes: '', clientId: '' },
  });

  const [record, setRecord] = useState<Lead | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [eventsNonce, setEventsNonce] = useState(0);
  const [loading, setLoading] = useState(true);
  const [converting, setConverting] = useState(false);

  const reset = useCallback(
    (l: Lead) =>
      form.reset({
        title: l.title ?? '',
        source: l.source ?? '',
        contactName: l.contactName ?? '',
        contactEmail: l.contactEmail ?? '',
        contactPhone: l.contactPhone ?? '',
        notes: l.notes ?? '',
        clientId: l.clientId ?? '',
      }),
    [form],
  );

  const load = useCallback(() => {
    return emsService.getLead(leadId).then((l) => {
      setRecord(l);
      reset(l);
    });
  }, [leadId, reset]);

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    emsService.clientOptions().then((rows) => active && setClients(rows));
    return () => {
      active = false;
    };
  }, [load]);

  const values = form.watch();
  const statusLabel = useMemo(() => {
    const s = engine.graph?.statuses.find((x) => x.id === record?.statusId);
    return s?.label ?? '';
  }, [engine.graph, record?.statusId]);

  const config = useMemo<ResourceFormConfig<Lead> | null>(() => {
    if (!record) return null;

    const wonId = engine.graph?.statuses.find((s) => s.key === 'won')?.id;
    const moves = record.statusId
      ? (engine.graph?.transitions ?? []).filter((t) => t.fromStatusId === record.statusId)
      : [];
    // Win is a plain status move; "Create event" is separate + repeatable on a Won lead.
    const isWon = !!wonId && record.statusId === wonId;
    const statusName = (id: string) =>
      engine.graph?.statuses.find((s) => s.id === id)?.label ?? id;

    const actions: ResourceAction<Lead>[] = [
      ...(isWon
        ? [
            {
              id: 'create-event',
              label: 'Create event',
              icon: CalendarPlus,
              surfaces: { row: false, form: true, bulk: false },
              permission: 'crm_leads.manage',
              run: () => setConverting(true),
            } as ResourceAction<Lead>,
          ]
        : []),
      ...moves.map((t) => ({
          id: `move-${t.toStatusId}`,
          label: `${statusName(t.toStatusId)}`,
          icon: ArrowRight,
          surfaces: { row: false, form: true, bulk: false },
          permission: 'crm_leads.manage',
          run: async (_rows: Lead[], runtime: { reload: () => void }) => {
            try {
              await emsService.transitionLead(record.id, t.toStatusId);
              runtime.reload();
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Could not change the status.');
            }
          },
        })),
    ];

    return {
      breadcrumb: [{ label: labelPlural('lead'), href: '/ems/leads' }, { label: record.title }],
      backHref: '/ems/leads',
      backLabel: labelPlural('lead'),
      title: record.title,
      subtitle: record.source ?? undefined,
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
              <Row label="Title">
                {editing ? (
                  <Input
                    aria-label="Title"
                    value={values.title}
                    onChange={(e) => form.setValue('title', e.target.value, { shouldDirty: true })}
                  />
                ) : (
                  <span className="text-sm">{values.title || '—'}</span>
                )}
              </Row>
              <Row label="Client">
                {editing ? (
                  <SearchSelect
                    value={values.clientId || null}
                    onChange={(v) => form.setValue('clientId', v || '', { shouldDirty: true })}
                    options={clients.map((c) => ({ value: c.id, label: c.name }))}
                    placeholder="Link a client…"
                  />
                ) : values.clientId ? (
                  <Link
                    href={`/ems/clients/${values.clientId}`}
                    className="text-sm text-primary hover:underline"
                  >
                    {clients.find((c) => c.id === values.clientId)?.name || 'View client'}
                  </Link>
                ) : (
                  <span className="text-sm">—</span>
                )}
              </Row>
              {(
                [
                  ['source', 'Source'],
                  ['contactName', 'Contact name'],
                  ['contactEmail', 'Contact email'],
                  ['contactPhone', 'Contact phone'],
                  ['notes', 'Notes'],
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
          id: 'events',
          label: labelPlural('project'),
          icon: CalendarPlus,
          render: () => <RelatedEvents leadId={record.id} nonce={eventsNonce} />,
        },
      ],
      actions,
      actionRows: [record],
      onReload: () => load(),
      editable: true,
      editPermission: 'crm_leads.manage',
      isDirty: form.formState.isDirty,
      onSave: async () => {
        const updated = await emsService.updateLead(record.id, {
          title: values.title,
          source: values.source,
          contactName: values.contactName,
          contactEmail: values.contactEmail,
          contactPhone: values.contactPhone,
          notes: values.notes,
          clientId: values.clientId || null,
        });
        setRecord(updated);
        reset(updated);
        return true;
      },
      onCancel: () => reset(record),
    };
  }, [record, engine.graph, values, form, statusLabel, labelPlural, load, reset, clients, eventsNonce]);

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
        <div className="py-24 text-center text-sm font-medium">Lead not found.</div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
      {converting && record && (
        <ConvertDialog
          lead={record}
          onClose={() => setConverting(false)}
          onDone={() => {
            setConverting(false);
            setEventsNonce((n) => n + 1); // repeatable — refresh the Events tab
          }}
        />
      )}
    </Container>
  );
}

function ConvertDialog({
  lead,
  onClose,
  onDone,
}: {
  lead: Lead;
  onClose: () => void;
  onDone: () => void;
}) {
  const [templates, setTemplates] = useState<{ value: string; label: string }[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    emsService
      .listTemplates({ pageSize: 200 })
      .then((p) => setTemplates(p.items.map((t) => ({ value: t.id, label: t.name }))))
      .catch(() => setTemplates([]));
  }, []);

  const convert = async () => {
    if (!templateId) return;
    setBusy(true);
    setError(null);
    try {
      await emsService.createEventFromLead(lead.id, { templateId });
      toast.success('Event created from this lead.');
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the event.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Create event — {lead.title}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label>Event template *</Label>
            <SearchSelect
              value={templateId}
              onChange={setTemplateId}
              options={templates}
              placeholder="Pick a template…"
              emptyText="No event templates yet"
            />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void convert()} disabled={!templateId || busy}>
            {busy ? 'Creating…' : 'Create event'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RelatedEvents({ leadId, nonce }: { leadId: string; nonce: number }) {
  const config = useMemo(
    () =>
      embeddedListConfig<LeadEvent>({
        viewKey: 'lead_events',
        getRowId: (r) => r.id,
        rowHref: (r) => `/ems/events/${r.id}`,
        searchPlaceholder: 'Search events…',
        fetcher: async () => {
          const rows = await emsService.leadEvents(leadId);
          return { data: rows, total: rows.length, page: 0 };
        },
        columns: [
          {
            id: 'title',
            accessorKey: 'title',
            header: 'Title',
            cell: ({ row }) => <span className="font-medium">{row.original.title || 'Event'}</span>,
          },
        ],
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [leadId, nonce],
  );
  return <ResourceList config={config} />;
}
