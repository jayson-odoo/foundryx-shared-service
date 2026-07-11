'use client';

/**
 * Circular prev/next record-nav for the Developer Logs detail (sprint-4/12
 * enhancement — matches the Users/submission ResourceForm "‹ N / M ›" pager).
 *
 * Fetches the ordered id list from the SAME list query in the list's default
 * order (createdAt desc), capped at the endpoint max page size (200 — the
 * submission record-nav precedent). Neighbours wrap circularly. UI → hook →
 * service.
 */
import { useEffect, useState } from 'react';
import { integrationLogService } from '@/services/integration-log-service';

const NAV_PAGE_SIZE = 200; // endpoint cap (GET /integration-logs page_size ≤ 200)

export interface IntegrationLogNavState {
  index: number; // 0-based position of the current log, or -1 if not in the window
  total: number;
  prevId: string | null; // circular neighbour toward newer/older
  nextId: string | null;
}

export function useIntegrationLogNav(logId: string): IntegrationLogNavState {
  const [ids, setIds] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    integrationLogService
      .list({ page: 0, pageSize: NAV_PAGE_SIZE })
      .then((res) => {
        if (!cancelled) setIds(res.data.map((r) => r.id));
      })
      .catch(() => {
        if (!cancelled) setIds([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const index = ids.indexOf(logId);
  const total = ids.length;
  if (index < 0 || total <= 1) {
    return { index, total, prevId: null, nextId: null };
  }
  return {
    index,
    total,
    prevId: ids[(index - 1 + total) % total],
    nextId: ids[(index + 1) % total],
  };
}
