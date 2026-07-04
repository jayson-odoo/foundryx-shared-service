import { apiFetch } from '@/lib/api-client';
import { toCsv } from '@/lib/csv';
import type { ListQuery, ListResult } from '@/types/resource';
import type { EmailLogDetail, EmailLogListItem } from '@/types/templates';
import type { EmailLogService } from './email-log-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  if (query.segment) p.set('segment', query.segment);
  return p;
}

export const realEmailLogService: EmailLogService = {
  list(query: ListQuery): Promise<ListResult<EmailLogListItem>> {
    return apiFetch<ListResult<EmailLogListItem>>(`/emails?${listParams(query).toString()}`);
  },

  get(id: string): Promise<EmailLogDetail | null> {
    return apiFetch<EmailLogDetail>(`/emails/${id}`).catch(() => null);
  },

  getAt(query: ListQuery, index: number) {
    const p = listParams(query);
    p.delete('page');
    p.delete('page_size');
    p.set('index', String(index));
    return apiFetch<{ email: EmailLogListItem | null; total: number }>(
      `/emails/at?${p.toString()}`,
    );
  },

  retry(id: string): Promise<EmailLogListItem> {
    return apiFetch<EmailLogListItem>(`/emails/${id}/retry`, { method: 'POST' });
  },

  cancel(id: string): Promise<EmailLogListItem> {
    return apiFetch<EmailLogListItem>(`/emails/${id}/cancel`, { method: 'POST' });
  },

  async export(query: ListQuery, columns: string[]): Promise<string> {
    const full = await this.list({ ...query, page: 0, pageSize: 200 });
    const rows = full.data.map((r) =>
      columns.map((c) => String((r as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return toCsv(columns, rows);
  },
};
