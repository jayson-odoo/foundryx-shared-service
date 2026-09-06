/**
 * Pins the S0 mock to the UAC's seeded report fixture (plan 30,
 * `30-omnichannel-dashboard-reports-acceptance-criteria.md`) - the numbers
 * here are copied verbatim from the AC text (AC-RPT-01..07, 18, 19, 21, 23,
 * 26) so a future edit to the mock can't silently drift from the contract
 * the real S1-S3 backend will also have to satisfy.
 */
import { describe, expect, it } from 'vitest';
import { mockOmnichannelReportService } from './omnichannel-report-service.mock';
import type {
  AssignmentLogRow,
  ConversationsReportTotals,
  MessagesReportTotals,
  ResponseBucketRow,
} from '@/types/omnichannel';

const WS = 'ws-1';
const RANGE = { from: '2026-03-01', to: '2026-03-07' };
const KL = 'Asia/Kuala_Lumpur';

describe('mockOmnichannelReportService - dashboard (fixture)', () => {
  it('AC-RPT-01: current-state tiles ignore the range', async () => {
    const res = await mockOmnichannelReportService.dashboard(WS, { ...RANGE, tz: KL });
    expect(res.tiles).toEqual({ open: 2, assigned: 1, unassigned: 2, snoozed: 1 });
  });

  it('AC-RPT-02: lifecycle stage counts + percent', async () => {
    const res = await mockOmnichannelReportService.dashboard(WS, { ...RANGE, tz: KL });
    const byLabel = Object.fromEntries(res.lifecycle.map((s) => [s.label, s]));
    expect(byLabel['New Lead']).toMatchObject({ count: 4, percent: 50 });
    expect(byLabel['Hot Lead']).toMatchObject({ count: 2, percent: 25 });
    expect(byLabel['Payment']).toMatchObject({ count: 1, percent: 12.5 });
    expect(byLabel['Customer']).toMatchObject({ count: 1, percent: 12.5 });
    expect(byLabel['Cold Lead']).toMatchObject({ count: 0, percent: 0 });
  });

  it('AC-RPT-03: opened/closed series bucket by LOCAL day in Asia/Kuala_Lumpur', async () => {
    const res = await mockOmnichannelReportService.dashboard(WS, { ...RANGE, tz: KL });
    expect(res.buckets.map((b) => b.key)).toEqual([
      '2026-03-01',
      '2026-03-02',
      '2026-03-03',
      '2026-03-04',
      '2026-03-05',
      '2026-03-06',
      '2026-03-07',
    ]);
    expect(res.series.opened).toEqual([2, 2, 1, 0, 1, 1, 0]);
    expect(res.series.closed).toEqual([1, 2, 1, 1, 0, 1, 0]);
  });

  it('AC-RPT-04: the SAME rows bucket differently under tz=UTC', async () => {
    const res = await mockOmnichannelReportService.dashboard(WS, { ...RANGE, tz: 'UTC' });
    expect(res.series.opened).toEqual([3, 1, 1, 0, 2, 0, 0]);
    expect(res.series.closed).toEqual([1, 2, 1, 1, 0, 1, 0]);
  });

  it('AC-RPT-05/06: response + resolution totals, incl. the derived-from-messages datapoint', async () => {
    const res = await mockOmnichannelReportService.dashboard(WS, { ...RANGE, tz: KL });
    expect(res.responseTotals).toEqual({
      medianSeconds: 150,
      p90Seconds: 660,
      averageSeconds: 278,
      sampleCount: 6,
      derivedFromMessages: 1,
    });
    expect(res.resolutionTotals).toEqual({
      medianSeconds: 12600,
      p90Seconds: 278100,
      averageSeconds: 98100,
      sampleCount: 6,
    });
  });

  it('AC-RPT-07: topAgents ordered by closedCount desc then name asc', async () => {
    const res = await mockOmnichannelReportService.dashboard(WS, { ...RANGE, tz: KL });
    expect(res.topAgents).toEqual([
      { userId: 'u_ann', name: 'Ann Lee', closedCount: 4, medianResponseSeconds: 30 },
      { userId: 'u_ben', name: 'Ben Ooi', closedCount: 2, medianResponseSeconds: 420 },
    ]);
  });

  it('AC-RPT-14: an out-of-fixture range renders zeroes, not a crash', async () => {
    const res = await mockOmnichannelReportService.dashboard(WS, { from: '2020-01-01', to: '2020-01-02', tz: KL });
    expect(res.series.opened.every((n) => n === 0)).toBe(true);
    expect(res.responseTotals).toMatchObject({ medianSeconds: null, sampleCount: 0 });
    expect(res.topAgents).toEqual([]);
  });
});

describe('mockOmnichannelReportService - reports (fixture)', () => {
  it('AC-RPT-18: conversations series + totals', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'conversations', { ...RANGE, tz: KL });
    expect(res.series).toEqual([
      { key: 'opened', label: 'Opened', points: [2, 2, 1, 0, 1, 1, 0] },
      { key: 'closed', label: 'Closed', points: [1, 2, 1, 1, 0, 1, 0] },
      { key: 'reopened', label: 'Reopened', points: [0, 0, 0, 1, 0, 0, 0] },
    ]);
    expect(res.totals as ConversationsReportTotals).toEqual({ opened: 7, closed: 6, reopened: 1 });
  });

  it('AC-RPT-19: responses distribution + totals', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'responses', { ...RANGE, tz: KL });
    expect(res.totals).toEqual({
      medianSeconds: 150,
      p90Seconds: 660,
      averageSeconds: 278,
      sampleCount: 6,
      derivedFromMessages: 1,
    });
    expect(res.rows as ResponseBucketRow[]).toEqual([
      { bucket: 'lt30s', label: '< 30s', count: 1, percent: 16.7 },
      { bucket: '30s-2m', label: '30s - 2m', count: 1, percent: 16.7 },
      { bucket: '2m-5m', label: '2m - 5m', count: 2, percent: 33.3 },
      { bucket: '5m-10m', label: '5m - 10m', count: 1, percent: 16.7 },
      { bucket: '10m-30m', label: '10m - 30m', count: 1, percent: 16.7 },
      { bucket: '30m-1h', label: '30m - 1h', count: 0, percent: 0 },
      { bucket: 'gt1h', label: '> 1h', count: 0, percent: 0 },
    ]);
  });

  it('AC-RPT-20: responses grouped by user', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'responses', { ...RANGE, tz: KL, groupBy: 'user' });
    const byUser = Object.fromEntries((res.rows as { userId: string; sampleCount: number; medianSeconds: number | null }[]).map((r) => [r.userId, r]));
    expect(byUser.u_ann).toMatchObject({ sampleCount: 3, medianSeconds: 30 });
    expect(byUser.u_ben).toMatchObject({ sampleCount: 3, medianSeconds: 420 });
  });

  it('AC-RPT-21/22: resolutions close-reason breakdown + totals', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'resolutions', { ...RANGE, tz: KL });
    expect(res.totals).toEqual({ medianSeconds: 12600, p90Seconds: 278100, averageSeconds: 98100, sampleCount: 6 });
    const byName = Object.fromEntries((res.rows as { name: string | null; count: number; percent: number }[]).map((r) => [r.name, r]));
    expect(byName['General Inquiry']).toMatchObject({ count: 2, percent: 33.3 });
    expect(byName['Sales Inquiry']).toMatchObject({ count: 1, percent: 16.7 });
    expect(byName['Payment Issue']).toMatchObject({ count: 1, percent: 16.7 });
    expect(byName['Others']).toMatchObject({ count: 2, percent: 33.3 });
  });

  it('AC-RPT-23: messages series (SYSTEM notes count in neither direction) + channel breakdown', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'messages', { ...RANGE, tz: KL });
    expect(res.series).toEqual([
      { key: 'incoming', label: 'Incoming', points: [2, 2, 0, 1, 1, 0, 0] },
      { key: 'outgoing', label: 'Outgoing', points: [2, 2, 0, 1, 1, 0, 0] },
    ]);
    expect(res.totals as MessagesReportTotals).toEqual({ incoming: 6, outgoing: 6 });

    const grouped = await mockOmnichannelReportService.report(WS, 'messages', { ...RANGE, tz: KL, groupBy: 'channel' });
    expect(grouped.rows).toEqual([{ channelId: 'chn-wa', name: 'WhatsApp Demo', channelType: 'WHATSAPP', incoming: 6, outgoing: 6 }]);
  });

  it('AC-RPT-24: users report rows incl. the zero-activity member', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'users', { ...RANGE, tz: KL, pageSize: 10 });
    const byId = Object.fromEntries((res.rows as { userId: string }[]).map((r) => [r.userId, r]));
    expect(byId.u_ann).toMatchObject({ assignedCount: 1, closedCount: 4, messagesSent: 3, commentsCount: 1 });
    expect(byId.u_ben).toMatchObject({ assignedCount: 1, closedCount: 2, messagesSent: 3, commentsCount: 0 });
    expect(byId.u_cara).toMatchObject({
      assignedCount: 0,
      closedCount: 0,
      messagesSent: 0,
      medianFirstResponseSeconds: null,
      medianResolutionSeconds: null,
    });
  });

  it('AC-RPT-25: leaderboard ranks users report rows', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'leaderboard', { ...RANGE, tz: KL, pageSize: 10 });
    const rows = res.rows as { userId: string; rank: number }[];
    expect(rows[0]).toMatchObject({ userId: 'u_ann', rank: 1 });
    expect(rows[1]).toMatchObject({ userId: 'u_ben', rank: 2 });
    expect(rows[2]).toMatchObject({ userId: 'u_cara', rank: 3 });
  });

  it('AC-RPT-26: assignment log - series, totals and a paginated newest-first log of 3', async () => {
    const res = await mockOmnichannelReportService.report(WS, 'assignments', { ...RANGE, tz: KL, pageSize: 10 });
    expect(res.series).toEqual([{ key: 'assigned', label: 'Assigned', points: [1, 1, 0, 0, 0, 0, 0] }]);
    expect(res.totals).toEqual({ assigned: 2, unassigned: 1 });
    expect(res.total).toBe(3);
    const rows = res.rows as AssignmentLogRow[];
    expect(rows[0].eventType).toBe('unassigned'); // newest first
    expect(rows.map((r) => r.eventType).sort()).toEqual(['assigned', 'assigned', 'unassigned']);
  });
});

describe('mockOmnichannelReportService - export', () => {
  it('resolves CSV text for a bounded/filtered export', async () => {
    const csv = await mockOmnichannelReportService.exportReport(WS, 'conversations', { ...RANGE, tz: KL, userId: 'u_ann' });
    expect(csv.split('\n')[0]).toBe('"Bucket","Opened","Closed","Reopened"');
  });

  it('throws ExportPendingError for an unfiltered export with enough rows', async () => {
    // The 7-bucket response-time distribution always has > 5 rows -
    // demonstrates the wait-window -> Jobs fallback deterministically.
    await expect(mockOmnichannelReportService.exportReport(WS, 'responses', { ...RANGE, tz: KL })).rejects.toThrow(
      /still running/,
    );
  });
});
