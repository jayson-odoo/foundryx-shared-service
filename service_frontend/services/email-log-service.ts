import type { ListQuery, ListResult } from '@/types/resource';
import type { EmailLogDetail, EmailLogListItem } from '@/types/templates';
import { realEmailLogService } from './email-log-service.real';

/** Email log segments (D14) — 'all' | lowercase outbox status. */
export type EmailLogSegment = 'all' | 'pending' | 'sent' | 'failed' | 'cancelled';

export const EMAIL_LOG_SEGMENTS: { id: EmailLogSegment; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'pending', label: 'Pending' },
  { id: 'sent', label: 'Sent' },
  { id: 'failed', label: 'Failed' },
  { id: 'cancelled', label: 'Cancelled' },
];

export interface EmailLogService {
  /** Segment rides ListQuery.segment (shell N-way segments). */
  list(query: ListQuery): Promise<ListResult<EmailLogListItem>>;
  get(id: string): Promise<EmailLogDetail | null>;
  /** Record-nav: the row at `index` within the full result set of `query`. */
  getAt(query: ListQuery, index: number): Promise<{ email: EmailLogListItem | null; total: number }>;
  /** FAILED|CANCELLED → PENDING (next attempt now; attempts preserved). */
  retry(id: string): Promise<EmailLogListItem>;
  /** PENDING → CANCELLED (atomic backend guard; 409 once claimed). */
  cancel(id: string): Promise<EmailLogListItem>;
  export(query: ListQuery, columns: string[]): Promise<string>;
}

// Phase B: real api-client implementation (one-line boundary).
export const emailLogService: EmailLogService = realEmailLogService;
