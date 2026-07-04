import { toCsv } from '@/lib/csv';
import { newDocId } from '@/lib/template-doc';
import type { ListQuery, ListResult } from '@/types/resource';
import type { EmailLogDetail, EmailLogListItem, EmailOutboxStatus } from '@/types/templates';
import type { EmailLogService } from './email-log-service';

const LATENCY_MS = 250;

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}

const SAMPLE_HTML = (subject: string, link: string) =>
  `<!doctype html><html><body style="margin:0;font-family:Arial,sans-serif;background:#F4F4F5"><div style="max-width:600px;margin:0 auto;background:#fff"><div style="background:#FF5A00;padding:16px 24px"><span style="color:#fff;font-weight:700">Acme Events</span></div><div style="padding:24px"><h2 style="margin:0 0 8px">${subject}</h2><p style="font-size:14px;line-height:1.6">Hi Alex, here is your link.</p><a href="${link}" style="display:inline-block;background:#FF5A00;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none">Open</a></div><div style="background:#18181B;padding:24px;text-align:center"><span style="color:#A1A1AA;font-size:12px">Acme Events · 1 Example Street</span></div></div></body></html>`;

function seedRows(): EmailLogDetail[] {
  const mins = (n: number) => new Date(Date.now() - n * 60_000).toISOString();
  const make = (
    n: number,
    status: EmailOutboxStatus,
    templateKey: string,
    subject: string,
    extra?: Partial<EmailLogDetail>,
  ): EmailLogDetail => ({
    id: newDocId('eml'),
    toEmail: `user${n}@example.com`,
    subject,
    templateKey,
    status,
    attempts: status === 'SENT' ? 1 : status === 'FAILED' ? 3 : 0,
    usedFallback: false,
    createdAt: mins(n * 7 + 5),
    sentAt: status === 'SENT' ? mins(n * 7 + 3) : null,
    nextAttemptAt: status === 'PENDING' ? mins(-10) : null,
    htmlBody: SAMPLE_HTML(subject, 'https://acme.foundryxems.com/change-password?token=sample'),
    textBody: `${subject}\n\nHi Alex, here is your link:\nhttps://acme.foundryxems.com/change-password?token=sample`,
    lastError: status === 'FAILED' ? 'SMTPConnectError: connection refused by smtp.acme.com:587' : null,
    connectionId: status === 'SENT' ? 'conn-platform-smtp' : null,
    ...extra,
  });

  return [
    make(1, 'PENDING', 'auth.invite', "You've been invited to Acme Events"),
    make(2, 'SENT', 'auth.password_reset', 'Reset your Acme Events password'),
    make(3, 'SENT', 'account.email_change_verify', 'Verify your new email address'),
    make(4, 'FAILED', 'auth.password_reset', 'Reset your Acme Events password'),
    make(5, 'SENT', 'tenant.provisioned', 'Welcome to Acme Events', { usedFallback: true }),
    make(6, 'CANCELLED', 'auth.invite', "You've been invited to Acme Events"),
    make(7, 'SENT', 'template.test', '[Test] Password reset'),
    make(8, 'FAILED', 'status.notification', 'Acme Events moved to Suspended'),
    make(9, 'SENDING', 'auth.invite', "You've been invited to Acme Events"),
    make(10, 'SENT', 'auth.invite', "You've been invited to Acme Events"),
  ];
}

let rows: EmailLogDetail[] = seedRows();

function toListItem(r: EmailLogDetail): EmailLogListItem {
  return {
    id: r.id,
    toEmail: r.toEmail,
    subject: r.subject,
    templateKey: r.templateKey,
    status: r.status,
    attempts: r.attempts,
    usedFallback: r.usedFallback,
    createdAt: r.createdAt,
    sentAt: r.sentAt,
    nextAttemptAt: r.nextAttemptAt,
  };
}

export const mockEmailLogService: EmailLogService = {
  list(query: ListQuery): Promise<ListResult<EmailLogListItem>> {
    let data = rows.map(toListItem);
    const segment = query.segment;
    if (segment && segment !== 'all') {
      data = data.filter((r) => r.status === segment.toUpperCase());
    }
    if (query.search) {
      const q = query.search.toLowerCase();
      data = data.filter(
        (r) =>
          r.toEmail.toLowerCase().includes(q) ||
          r.subject.toLowerCase().includes(q) ||
          r.templateKey.toLowerCase().includes(q),
      );
    }
    if (query.sort) {
      const { id, desc } = query.sort;
      data = [...data].sort((a, b) => {
        const av = String((a as unknown as Record<string, unknown>)[id] ?? '');
        const bv = String((b as unknown as Record<string, unknown>)[id] ?? '');
        return desc ? bv.localeCompare(av) : av.localeCompare(bv);
      });
    } else {
      data = [...data].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    }
    const total = data.length;
    const start = query.page * query.pageSize; // ListQuery.page is 0-based
    return delay({ data: data.slice(start, start + query.pageSize), total, page: query.page });
  },

  get(id: string): Promise<EmailLogDetail | null> {
    return delay(rows.find((r) => r.id === id) ?? null);
  },

  async getAt(query: ListQuery, index: number) {
    const full = await this.list({ ...query, page: 0, pageSize: 10_000 });
    return { email: full.data[index] ?? null, total: full.total };
  },

  retry(id: string): Promise<EmailLogListItem> {
    const row = rows.find((r) => r.id === id);
    if (!row) return Promise.reject(new Error('Email not found.'));
    if (row.status !== 'FAILED' && row.status !== 'CANCELLED') {
      return Promise.reject(new Error('Only failed or cancelled emails can be retried.'));
    }
    // Attempts counter keeps counting — history stays honest (D14).
    row.status = 'PENDING';
    row.nextAttemptAt = new Date().toISOString();
    row.lastError = null;
    return delay(toListItem(row));
  },

  cancel(id: string): Promise<EmailLogListItem> {
    const row = rows.find((r) => r.id === id);
    if (!row) return Promise.reject(new Error('Email not found.'));
    // Atomic WHERE status = PENDING — dispatcher lease wins the race (D14).
    if (row.status !== 'PENDING') {
      return Promise.reject(new Error('Email is already sending or sent — too late to cancel.'));
    }
    row.status = 'CANCELLED';
    row.nextAttemptAt = null;
    return delay(toListItem(row));
  },

  export(query: ListQuery, columns: string[]): Promise<string> {
    let data = rows.map(toListItem);
    const segment = query.segment;
    if (segment && segment !== 'all') data = data.filter((r) => r.status === segment.toUpperCase());
    const body = data.map((r) =>
      columns.map((c) => String((r as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return delay(toCsv(columns, body));
  },
};

/** Test hook — reset the in-memory store between Vitest cases. */
export function __resetMockEmailLog(): void {
  rows = seedRows();
}
