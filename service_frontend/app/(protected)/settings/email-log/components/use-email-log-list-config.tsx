'use client';

import { useMemo } from 'react';
import { Ban } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { useFx } from '@/hooks/use-fx';
import { FxListMoment } from '@/components/fx/pages/w3-logs/fx-log-parts';
import { emailLogService, EMAIL_LOG_SEGMENTS } from '@/services/email-log-service';
import type { EmailLogListItem } from '@/types/templates';
import { EMAIL_STATUS_REGISTRY, emailLogDetailPath } from './email-status';
import { useEmailLogActions } from './use-email-log-actions';

/** Other Action icons under the Foundryx UIUX switch (one icon per meaning). */
export const EMAIL_LOG_FX_ICONS = {
  retry: 'refresh' as const,
  cancel: <Ban aria-hidden="true" className="size-[18px]" />,
};

export function useEmailLogListConfig(): ResourceListConfig<EmailLogListItem> {
  const actions = useEmailLogActions();
  const { formatDateTime } = useDatetime();
  const fx = useFx();

  return useMemo<ResourceListConfig<EmailLogListItem>>(
    () => ({
      viewKey: 'email-log',
      getRowId: (row) => row.id,
      rowHref: (row) => emailLogDetailPath(row.id),
      fetcher: (query) => emailLogService.list(query),
      exporter: (query, columns) => emailLogService.export(query, columns),
      searchPlaceholder: 'Search recipient, subject or template…',
      searchHints: ['Recipient email', 'Subject', 'Template key'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'email-log',
      segments: EMAIL_LOG_SEGMENTS,
      columns: [
        {
          id: 'toEmail',
          accessorFn: (row) => row.toEmail,
          meta: { headerTitle: 'To' },
          header: ({ column }) => <DataGridColumnHeader title="To" column={column} />,
          cell: ({ row }) => (
            <span className="font-medium text-foreground">{row.original.toEmail}</span>
          ),
          size: 200,
          enableSorting: true,
        },
        {
          id: 'subject',
          accessorFn: (row) => row.subject,
          meta: { headerTitle: 'Subject' },
          header: ({ column }) => <DataGridColumnHeader title="Subject" column={column} />,
          cell: ({ row }) => <ClampedText text={row.original.subject} lines={1} />,
          size: 280,
          enableSorting: true,
        },
        {
          id: 'templateKey',
          accessorFn: (row) => row.templateKey,
          meta: { headerTitle: 'Template' },
          header: ({ column }) => <DataGridColumnHeader title="Template" column={column} />,
          cell: ({ row }) => (
            <code className="text-xs text-muted-foreground">{row.original.templateKey}</code>
          ),
          size: 180,
          enableSorting: true,
        },
        {
          id: 'status',
          accessorFn: (row) => row.status,
          meta: { headerTitle: 'Status' },
          header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
          cell: ({ row }) => (
            <StatusBadge status={row.original.status} registry={EMAIL_STATUS_REGISTRY} size="sm" />
          ),
          size: 110,
          enableSorting: true,
        },
        {
          id: 'attempts',
          accessorFn: (row) => row.attempts,
          meta: { headerTitle: 'Attempts' },
          header: ({ column }) => <DataGridColumnHeader title="Attempts" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm text-muted-foreground">{row.original.attempts}</span>
          ),
          size: 90,
          enableSorting: true,
        },
        {
          id: 'createdAt',
          accessorFn: (row) => row.createdAt,
          meta: { headerTitle: 'Created' },
          header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
          cell: ({ row }) =>
            fx ? (
              <FxListMoment iso={row.original.createdAt} className="text-sm text-(--fx-ink-2)" />
            ) : (
              <span className="text-sm text-muted-foreground">
                {formatDateTime(row.original.createdAt)}
              </span>
            ),
          size: 160,
          enableSorting: true,
        },
        {
          id: 'sentAt',
          accessorFn: (row) => row.sentAt,
          meta: { headerTitle: 'Sent' },
          header: ({ column }) => <DataGridColumnHeader title="Sent" column={column} />,
          cell: ({ row }) =>
            fx ? (
              <FxListMoment iso={row.original.sentAt} className="text-sm text-(--fx-ink-2)" />
            ) : (
              <span className="text-sm text-muted-foreground">
                {row.original.sentAt ? formatDateTime(row.original.sentAt) : '-'}
              </span>
            ),
          size: 160,
          enableSorting: true,
        },
      ],
      filterFields: [
        { field: 'toEmail', label: 'To', type: 'text' },
        { field: 'subject', label: 'Subject', type: 'text' },
        { field: 'templateKey', label: 'Template key', type: 'text' },
        {
          field: 'status',
          label: 'Status',
          type: 'enum',
          options: Object.entries(EMAIL_STATUS_REGISTRY).map(([value, meta]) => ({
            label: meta.label,
            value,
          })),
        },
      ],
      exportColumns: [
        { id: 'toEmail', label: 'To' },
        { id: 'subject', label: 'Subject' },
        { id: 'templateKey', label: 'Template key' },
        { id: 'status', label: 'Status' },
        { id: 'attempts', label: 'Attempts' },
        { id: 'createdAt', label: 'Created' },
        { id: 'sentAt', label: 'Sent' },
      ],
      actions,
      // Foundryx UIUX switch only. Hold to Copy on the template key alone:
      // recipients and subjects are personal data and never copy.
      fx: {
        noun: 'emails',
        copyable: ['templateKey'],
        phoneHidden: ['attempts', 'sentAt'],
        cardLines: [['subject'], ['toEmail'], ['templateKey', 'createdAt']],
        iconFor: EMAIL_LOG_FX_ICONS,
      },
    }),
    [actions, formatDateTime, fx],
  );
}
