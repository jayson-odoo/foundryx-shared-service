'use client';

/** Admin — Registrations tab on the Event detail (sprint-4/05). Who registered
 * for this event: attendee, offering, seat, ticket status, paid, invoice. The
 * detail view renders the real signed QR (AC-05-TKT-02); row/form actions Void +
 * Refund kill the QR + release the seat (AC-05-TKT-04). */
import { useCallback, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { toast } from 'sonner';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { Ban, RotateCcw, Ticket } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { MasterDetail } from '@/components/platform/resource-master-detail';
import { ResourceForm } from '@/components/platform/resource-form';
import { FormRow } from '@/components/platform/resource-form/form-row';
import { useDatetime } from '@/hooks/use-datetime';
import { eventBillingService } from '@/services/event-billing-service';
import { emsService } from '@/services/ems-service';
import { formatMoney } from '@/lib/money';
import type { EventRegistration } from '@/types/registration';
import type { ListResult as LR } from '@/types/resource';
import { AddAttendeeDialog } from './add-attendee-dialog';

/** Ticket states that can no longer be voided/refunded (foolproof-UI). */
const TERMINAL_TICKET_KEYS = new Set(['void', 'refunded', 'transferred']);

/** Stop a row-action click from also opening the master-detail. */
const stop = (e: React.MouseEvent) => e.stopPropagation();

function PaidBadge({ paid }: { paid: boolean }) {
  return paid ? (
    <Badge variant="success" appearance="light" size="sm">Paid</Badge>
  ) : (
    <Badge variant="warning" appearance="light" size="sm">Unpaid</Badge>
  );
}

export function RegistrationsTab({ projectId }: { projectId: string }) {
  const { formatDateTime } = useDatetime();
  const [nonce, setNonce] = useState(0);
  const [adding, setAdding] = useState(false);
  const onCreate = useCallback(() => setAdding(true), []);

  const actions = useMemo<ResourceAction<EventRegistration>[]>(() => {
    const active = (rows: EventRegistration[]) =>
      rows.length === 1 && !TERMINAL_TICKET_KEYS.has(rows[0].ticketStatusKey);
    return [
      {
        id: 'void',
        label: 'Void',
        icon: Ban,
        tone: 'destructive',
        surfaces: { row: true, form: true },
        permission: 'tickets.manage',
        isVisible: active,
        confirm: {
          title: 'Void this ticket?',
          description:
            'The QR is killed (it can no longer be scanned) and any reserved seat is released. This cannot be undone.',
          confirmLabel: 'Void ticket',
        },
        run: async (rows, runtime) => {
          try {
            await emsService.voidTicket(projectId, rows[0].id);
            toast.success('Ticket voided.');
            runtime.reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not void the ticket.');
          }
        },
      },
      {
        id: 'refund',
        label: 'Refund',
        icon: RotateCcw,
        tone: 'destructive',
        surfaces: { row: true, form: true },
        permission: 'tickets.manage',
        isVisible: active,
        confirm: {
          title: 'Refund this ticket?',
          description:
            'The QR is killed and any reserved seat is released. The payment reversal is handled separately.',
          confirmLabel: 'Refund ticket',
        },
        run: async (rows, runtime) => {
          try {
            await emsService.refundTicket(projectId, rows[0].id);
            toast.success('Ticket refunded.');
            runtime.reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not refund the ticket.');
          }
        },
      },
    ];
  }, [projectId]);

  const config = useMemo<ResourceListConfig<EventRegistration>>(() => {
    const columns: ColumnDef<EventRegistration>[] = [
      {
        id: 'attendee',
        accessorFn: (r) => r.attendeeName,
        header: ({ column }) => <DataGridColumnHeader title="Attendee" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium">{row.original.attendeeName}</span>
            <span className="text-xs text-muted-foreground">{row.original.attendeeEmail}</span>
          </div>
        ),
        size: 220,
        enableSorting: false,
      },
      {
        id: 'offering',
        accessorFn: (r) => r.offeringName,
        header: ({ column }) => <DataGridColumnHeader title="Offering" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.offeringName}</span>,
        size: 170,
        enableSorting: false,
      },
      {
        id: 'seat',
        accessorFn: (r) => r.seatLabel,
        header: ({ column }) => <DataGridColumnHeader title="Seat" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.seatLabel ?? '—'}</span>,
        size: 80,
        enableSorting: false,
      },
      {
        id: 'ticket',
        accessorFn: (r) => r.ticketStatus,
        header: ({ column }) => <DataGridColumnHeader title="Ticket" column={column} />,
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light" size="sm">{row.original.ticketStatus}</Badge>
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'paid',
        accessorFn: (r) => r.paid,
        header: ({ column }) => <DataGridColumnHeader title="Payment" column={column} />,
        cell: ({ row }) => <PaidBadge paid={row.original.paid} />,
        size: 100,
        enableSorting: false,
      },
      {
        id: 'invoice',
        accessorFn: (r) => r.invoiceTotal,
        header: ({ column }) => <DataGridColumnHeader title="Invoice" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{formatMoney(row.original.invoiceTotal, row.original.currency)}</span>
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'registeredAt',
        accessorFn: (r) => r.registeredAt,
        header: ({ column }) => <DataGridColumnHeader title="Registered" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{formatDateTime(row.original.registeredAt)}</span>,
        size: 160,
        enableSorting: false,
      },
      // Row "…" so Void/Refund are reachable straight from the tickets list
      // (the table view doesn't auto-inject a row ActionMenu — matches the
      // clients/leads EMS list pattern). Detail "…" keeps the same actions.
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const reload = table.options.meta?.reload ?? (() => {});
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu actions={actions} rows={[row.original]} runtime={{ reload }} surface="row" />
            </div>
          );
        },
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];
    return {
      viewKey: 'ems.event.registrations',
      getRowId: (r) => r.id,
      rowHref: () => '#',
      fetcher: async (): Promise<LR<EventRegistration>> => {
        const rows = await eventBillingService.listRegistrations(projectId);
        return { data: rows, total: rows.length, page: 0 };
      },
      exporter: async () => '',
      searchPlaceholder: 'Search tickets…',
      searchHints: ['Attendee', 'Email'],
      enableStatusViews: false,
      createLabel: 'Add attendee',
      createPermission: 'offerings.manage',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [],
      actions,
    };
  }, [projectId, formatDateTime, onCreate, actions]);

  return (
    <>
      <MasterDetail
      key={nonce}
      config={config}
      detailRender={(r, nav) => (
        <ResourceForm
          config={{
            breadcrumb: [],
            backHref: '#',
            backLabel: 'Back to tickets',
            title: r.attendeeName,
            subtitle: r.offeringName,
            tabs: [
              {
                id: 'ticket',
                label: 'Ticket',
                icon: Ticket,
                render: () => (
                  <div className="grid max-w-3xl gap-6 sm:grid-cols-[1fr_auto] sm:items-start">
                    <div>
                      <FormRow label="Attendee">{r.attendeeName}</FormRow>
                      <FormRow label="Email">{r.attendeeEmail}</FormRow>
                      <FormRow label="Offering">{r.offeringName}</FormRow>
                      <FormRow label="Seat">{r.seatLabel ?? '—'}</FormRow>
                      <FormRow label="Ticket status">
                        <Badge variant="secondary" appearance="light" size="sm">{r.ticketStatus}</Badge>
                      </FormRow>
                      <FormRow label="Payment"><PaidBadge paid={r.paid} /></FormRow>
                      <FormRow label="Invoice">{formatMoney(r.invoiceTotal, r.currency)}</FormRow>
                    </div>
                    {/* real signed QR (AC-05-TKT-02) — scannable at the gate */}
                    <div className="flex flex-col items-center gap-2">
                      {r.qrToken && !TERMINAL_TICKET_KEYS.has(r.ticketStatusKey) ? (
                        <>
                          <div className="rounded-lg border border-border bg-white p-3">
                            <QRCodeSVG value={r.qrToken} size={160} aria-label="Ticket QR code" />
                          </div>
                          <span className="text-xs text-muted-foreground">Scan at the gate</span>
                        </>
                      ) : (
                        <div className="flex size-[160px] items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
                          QR unavailable
                        </div>
                      )}
                    </div>
                  </div>
                ),
              },
            ],
            actions,
            actionRows: [r],
            onReload: () => {
              nav.onBack();
              setNonce((n) => n + 1);
            },
            editable: false,
            isDirty: false,
            onSave: () => true,
            onCancel: () => {},
            embedded: true,
            onBack: nav.onBack,
            inlineNav: { index: nav.index, total: nav.total, onPrev: nav.onPrev, onNext: nav.onNext },
          }}
        />
      )}
      />
      {adding && (
        <AddAttendeeDialog
          projectId={projectId}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            setNonce((n) => n + 1);
          }}
        />
      )}
    </>
  );
}
