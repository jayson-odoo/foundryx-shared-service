'use client';

/**
 * Read-mode value renderer (plan sprint-3/01, D18) - the submission-view shape:
 * inputs are replaced by their FORMATTED answer values. Choice answers render
 * labels (not stored values), yesno → Yes/No, dates via the shared
 * `lib/datetime.ts` formatters (no raw `new Date(...).toLocaleString` -
 * house rule), files as name+size chips, signature as an <img>, repeater as a
 * small table, address stacked. Empty answers render an em-dash.
 */
import { formatDate, formatDateTime } from '@/lib/datetime';
import { Badge } from '@/components/ui/badge';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type {
  FormAddressAnswer,
  FormAnswerScalar,
  FormAnswerValue,
  FormField,
  FormFileAnswer,
} from '@/types/forms';
import { useState } from 'react';
import { Download } from 'lucide-react';
import { toast } from '@/lib/toast';
import { countryName } from './countries';
import { TableField } from './table-field';
import { useFileFetcher, useSubmissionId } from './submission-context';

export interface FieldReadProps {
  field: FormField;
  value: FormAnswerValue | undefined;
  /** Computed display value (for `computed` fields). */
  computed?: number | null;
}

const EMPTY = '-';

export function FieldRead({ field, value, computed }: FieldReadProps) {
  if (field.type === 'computed') {
    return <span>{computed === null || computed === undefined ? EMPTY : computed}</span>;
  }

  if (isEmpty(value) && !['address', 'repeater', 'table'].includes(field.type)) {
    return <span className="text-muted-foreground">{EMPTY}</span>;
  }

  switch (field.type) {
    case 'select':
    case 'radio':
      return <span>{choiceLabel(field, String(value)) || EMPTY}</span>;

    case 'multiselect':
    case 'checkboxes': {
      const values = Array.isArray(value) ? (value as string[]) : [];
      if (values.length === 0) return <span className="text-muted-foreground">{EMPTY}</span>;
      return (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => (
            <Badge key={v} variant="secondary" appearance="light" size="sm">
              {choiceLabel(field, v)}
            </Badge>
          ))}
        </div>
      );
    }

    case 'yesno':
      return <span>{value === true ? 'Yes' : value === false ? 'No' : EMPTY}</span>;

    case 'date':
      return <span>{formatDate(String(value))}</span>;

    case 'datetime':
      return <span>{formatDateTime(String(value))}</span>;

    case 'rating': {
      const max = field.rating?.max ?? 5;
      return <span>{`${value} / ${max}`}</span>;
    }

    case 'file': {
      const files = isFileList(value) ? value : [];
      if (files.length === 0) return <span className="text-muted-foreground">{EMPTY}</span>;
      return (
        <div className="flex flex-wrap gap-1">
          {files.map((f, i) => (
            <FileChip key={f.key} fieldKey={field.key ?? ''} index={i} label={`${f.name} (${formatBytes(f.size)})`} />
          ))}
        </div>
      );
    }

    case 'signature': {
      if (typeof value !== 'string' || !value) {
        return <span className="text-muted-foreground">{EMPTY}</span>;
      }
      // In-session capture is a PNG data-URL → preview inline.
      if (value.startsWith('data:')) {
        return (
          <img src={value} alt="Signature" className="max-h-32 rounded-md border border-border bg-background" />
        );
      }
      // A persisted submission stores a quarantine storage KEY - fetch it
      // authed (the serve route is CSP-sandboxed) and open the blob.
      return <FileChip fieldKey={field.key ?? ''} index={0} label="View signature" />;
    }

    case 'address':
      return <AddressRead value={isAddress(value) ? value : {}} />;

    case 'repeater':
      return <RepeaterRead field={field} value={Array.isArray(value) ? (value as Record<string, FormAnswerValue>[]) : []} />;

    case 'table':
      return (
        <TableField
          idBase={`read-${field.id}`}
          fieldKey={field.key ?? ''}
          columns={field.table?.columns ?? []}
          showRowNumbers={field.table?.showRowNumbers}
          value={Array.isArray(value) ? (value as Record<string, FormAnswerScalar>[]) : []}
          errors={{}}
          readOnly
          onChange={() => {}}
        />
      );

    case 'textarea':
      return <span className="whitespace-pre-wrap">{String(value)}</span>;

    default:
      return <span className="break-words">{String(value)}</span>;
  }
}

function AddressRead({ value }: { value: FormAddressAnswer }) {
  const lines = [
    value.line1,
    value.line2,
    [value.city, value.state, value.postcode].filter(Boolean).join(', '),
    countryName(value.country),
  ].filter((line) => line && line.trim());
  if (lines.length === 0) return <span className="text-muted-foreground">{EMPTY}</span>;
  return (
    <div className="space-y-0.5">
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </div>
  );
}

function RepeaterRead({
  field,
  value,
}: {
  field: FormField;
  value: Record<string, FormAnswerValue>[];
}) {
  const subs = field.repeater?.fields ?? [];
  if (value.length === 0) return <span className="text-muted-foreground">{EMPTY}</span>;
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            {subs.map((sub) => (
              <TableHead key={sub.id}>{sub.label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {value.map((row, i) => (
            <TableRow key={i}>
              {subs.map((sub) => {
                const cell = row[sub.key];
                let display: string;
                if (sub.type === 'yesno') display = cell === true ? 'Yes' : cell === false ? 'No' : EMPTY;
                else if (cell === null || cell === undefined || cell === '') display = EMPTY;
                else display = String(cell);
                return <TableCell key={sub.id}>{display}</TableCell>;
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---- helpers ----

function choiceLabel(field: FormField, value: string): string {
  return field.options?.items.find((o) => o.value === value)?.label ?? value;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isEmpty(value: FormAnswerValue | undefined): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

function isAddress(value: FormAnswerValue | undefined): value is FormAddressAnswer {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isFileList(value: FormAnswerValue | undefined): value is FormFileAnswer[] {
  return Array.isArray(value) && value.every((v) => !!v && typeof v === 'object' && 'key' in v && 'name' in v);
}

/** A clickable uploaded-file/signature chip. In read mode (submission context)
 * it fetches the authed serve route as a blob and opens it; without a
 * submission context (fill/preview) it's a plain label. */
function FileChip({ fieldKey, index, label }: { fieldKey: string; index: number; label: string }) {
  const submissionId = useSubmissionId();
  const fetchFile = useFileFetcher();
  const [loading, setLoading] = useState(false);

  // Clickable only when the page injected a session-bound blob fetcher (staff =
  // apiFetchBlob, portal = portalApiFetchBlob). Without one (fill/preview, or a
  // surface that didn't wire it) it's a plain label - never the staff client.
  if (!submissionId || !fetchFile) {
    return (
      <Badge variant="secondary" appearance="light" size="sm">
        {label}
      </Badge>
    );
  }

  const open = async () => {
    setLoading(true);
    try {
      const blob = await fetchFile(
        `/submissions/${submissionId}/files/${encodeURIComponent(fieldKey)}/${index}`,
      );
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      toast.error('Could not open the file.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={open}
      disabled={loading}
      className={cn(PRESSED_CLASS, 'inline-flex items-center gap-1 rounded-md border border-border bg-secondary/40 px-2 py-1 text-xs text-foreground transition-colors hover:bg-accent disabled:opacity-50')}
    >
      <Download className="size-3" /> {label}
    </button>
  );
}
