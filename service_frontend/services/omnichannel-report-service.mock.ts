/**
 * Frontend-first scaffolding behind the `omnichannel-report-service`
 * boundary (plan 30 S0), kept as the fixture for `omnichannel-report-
 * service.mock.test.ts` after S4 bound the real backend. Reproduces the
 * seeded UAC
 * fixture (`30-omnichannel-dashboard-reports-acceptance-criteria.md` §"Seeded
 * report fixture") - an in-memory event/message log bucketed with the SAME
 * shape of algorithm the backend will use (D-A9-8: bucket edges resolved in
 * `zoneinfo`-equivalent JS `Intl` math, applied as a conditional aggregate),
 * so the canonical fixture range (`from=2026-03-01&to=2026-03-07`) reproduces
 * the exact numbers the acceptance criteria assert for
 * `tz=Asia/Kuala_Lumpur` AND `tz=UTC`. Any other range/tz/granularity buckets
 * generically off the same events - not literally pinned to an AC number,
 * but not fabricated either, so every UI state (empty/loading/populated,
 * preset switches, filtering) is exercisable with no backend.
 */
import { toCsv } from '@/lib/csv';
import { ExportPendingError } from '@/lib/service-errors';
import type {
  AssignmentLogRow,
  AssignmentsReportTotals,
  CloseReasonRow,
  ConversationEventType,
  ConversationsReportTotals,
  DashboardLifecycleStage,
  DashboardResponse,
  DashboardTopAgent,
  DurationByUserRow,
  DurationStats,
  LeaderboardRow,
  MessageChannelRow,
  MessagesReportTotals,
  ReportBucket,
  ReportDescriptor,
  ReportExportRequest,
  ReportFilters,
  ReportGranularity,
  ReportKey,
  ReportMeta,
  ReportResponse,
  ReportSeries,
  ResponseBucketRow,
  UserReportRow,
  UsersReportTotals,
} from '@/types/omnichannel';
import type { OmnichannelReportService, ReportQuery } from './omnichannel-report-service';

const delay = <T>(v: T, ms = 250): Promise<T> => new Promise((resolve) => setTimeout(() => resolve(v), ms));

// ---------------------------------------------------------------------------
// Fixture data (verbatim from the UAC's "Seeded report fixture" table).
// ---------------------------------------------------------------------------

const USERS: Record<string, string> = {
  u_ann: 'Ann Lee',
  u_ben: 'Ben Ooi',
  u_cara: 'Cara Tan',
};

const CLOSE_REASONS: Record<string, string> = {
  general: 'General Inquiry',
  sales: 'Sales Inquiry',
  payment: 'Payment Issue',
  others: 'Others',
};

const CHANNEL = { id: 'chn-wa', name: 'WhatsApp Demo', channelType: 'WHATSAPP' as const };

interface FixtureEvent {
  id: string;
  contactId: string;
  type: ConversationEventType;
  at: string; // ISO Z
  actorUserId?: string | null;
  toValue?: string | null;
  fromValue?: string | null;
  closeReasonId?: string | null;
  responseSeconds?: number;
}

const FIXTURE_EVENTS: FixtureEvent[] = [
  { id: 'ev1', contactId: 'C1', type: 'opened', at: '2026-03-01T02:00:00Z' },
  { id: 'ev2', contactId: 'C1', type: 'first_agent_reply', at: '2026-03-01T02:00:30Z', actorUserId: 'u_ann', responseSeconds: 30 },
  { id: 'ev3', contactId: 'C1', type: 'closed', at: '2026-03-01T03:00:00Z', actorUserId: 'u_ann', closeReasonId: 'general' },
  { id: 'ev4', contactId: 'C2', type: 'opened', at: '2026-03-01T15:30:00Z' },
  { id: 'ev5', contactId: 'C2', type: 'assigned', at: '2026-03-01T15:40:00Z', actorUserId: 'u_ann', toValue: 'u_ann' },
  { id: 'ev6', contactId: 'C2', type: 'first_agent_reply', at: '2026-03-01T15:45:00Z', actorUserId: 'u_ben', responseSeconds: 900 },
  { id: 'ev7', contactId: 'C2', type: 'closed', at: '2026-03-02T02:00:00Z', actorUserId: 'u_ben', closeReasonId: 'sales' },
  { id: 'ev8', contactId: 'C3', type: 'opened', at: '2026-03-01T16:30:00Z' },
  { id: 'ev9', contactId: 'C3', type: 'first_agent_reply', at: '2026-03-01T16:32:00Z', actorUserId: 'u_ann', responseSeconds: 120 },
  { id: 'ev10', contactId: 'C4', type: 'opened', at: '2026-03-02T01:00:00Z' },
  { id: 'ev11', contactId: 'C4', type: 'assigned', at: '2026-03-02T01:05:00Z', actorUserId: 'u_ann', toValue: 'u_ben' },
  { id: 'ev12', contactId: 'C4', type: 'first_agent_reply', at: '2026-03-02T01:07:00Z', actorUserId: 'u_ben', responseSeconds: 420 },
  { id: 'ev13', contactId: 'C4', type: 'closed', at: '2026-03-02T05:00:00Z', actorUserId: 'u_ben', closeReasonId: 'payment' },
  { id: 'ev14', contactId: 'C5', type: 'opened', at: '2026-03-03T03:00:00Z' },
  { id: 'ev15', contactId: 'C5', type: 'closed', at: '2026-03-03T04:00:00Z', actorUserId: 'u_ann', closeReasonId: 'others' },
  { id: 'ev16', contactId: 'C5', type: 'reopened', at: '2026-03-04T03:00:00Z' },
  { id: 'ev17', contactId: 'C5', type: 'first_agent_reply', at: '2026-03-04T03:00:20Z', actorUserId: 'u_ann', responseSeconds: 20 },
  { id: 'ev18', contactId: 'C5', type: 'closed', at: '2026-03-04T06:00:00Z', actorUserId: 'u_ann', closeReasonId: 'general' },
  { id: 'ev19', contactId: 'C2', type: 'unassigned', at: '2026-03-04T08:00:00Z', actorUserId: 'u_ben', fromValue: 'u_ann' },
  { id: 'ev20', contactId: 'C6', type: 'opened', at: '2026-03-05T02:00:00Z' },
  { id: 'ev21', contactId: 'C6', type: 'comment_added', at: '2026-03-05T02:05:00Z', actorUserId: 'u_ann' },
  { id: 'ev22', contactId: 'C7', type: 'opened', at: '2026-03-05T16:10:00Z' },
  { id: 'ev23', contactId: 'C7', type: 'snoozed', at: '2026-03-05T17:00:00Z' },
  { id: 'ev24', contactId: 'C8', type: 'opened', at: '2026-02-28T02:00:00Z' },
  { id: 'ev25', contactId: 'C8', type: 'closed', at: '2026-03-06T02:00:00Z', actorUserId: 'u_ann', closeReasonId: 'others' },
];

interface FixtureMessage {
  id: string;
  contactId: string;
  sender: 'AGENT' | 'CONTACT' | 'SYSTEM';
  actorUserId?: string | null;
  at: string;
  channelId: string;
}

const FIXTURE_MESSAGES: FixtureMessage[] = [
  { id: 'm1', contactId: 'C1', sender: 'CONTACT', at: '2026-03-01T02:00:00Z', channelId: 'chn-wa' },
  { id: 'm2', contactId: 'C1', sender: 'AGENT', actorUserId: 'u_ann', at: '2026-03-01T02:00:30Z', channelId: 'chn-wa' },
  { id: 'm3', contactId: 'C2', sender: 'CONTACT', at: '2026-03-01T15:30:00Z', channelId: 'chn-wa' },
  { id: 'm4', contactId: 'C2', sender: 'AGENT', actorUserId: 'u_ben', at: '2026-03-01T15:45:00Z', channelId: 'chn-wa' },
  { id: 'm5', contactId: 'C3', sender: 'CONTACT', at: '2026-03-01T16:30:00Z', channelId: 'chn-wa' },
  { id: 'm6', contactId: 'C3', sender: 'AGENT', actorUserId: 'u_ann', at: '2026-03-01T16:32:00Z', channelId: 'chn-wa' },
  { id: 'm7', contactId: 'C4', sender: 'CONTACT', at: '2026-03-02T01:00:00Z', channelId: 'chn-wa' },
  { id: 'm8', contactId: 'C4', sender: 'AGENT', actorUserId: 'u_ben', at: '2026-03-02T01:07:00Z', channelId: 'chn-wa' },
  { id: 'm9', contactId: 'C5', sender: 'CONTACT', at: '2026-03-04T03:00:00Z', channelId: 'chn-wa' },
  { id: 'm10', contactId: 'C5', sender: 'AGENT', actorUserId: 'u_ann', at: '2026-03-04T03:00:20Z', channelId: 'chn-wa' },
  { id: 'm11', contactId: 'C6', sender: 'CONTACT', at: '2026-03-05T02:00:00Z', channelId: 'chn-wa' },
  { id: 'm12', contactId: 'C6', sender: 'AGENT', actorUserId: 'u_ben', at: '2026-03-05T02:03:00Z', channelId: 'chn-wa' },
  { id: 'm13', contactId: 'C6', sender: 'SYSTEM', actorUserId: 'u_ann', at: '2026-03-05T02:05:00Z', channelId: 'chn-wa' },
];

/** Ground truth of "now" per contact (tiles/lifecycle IGNORE `from`/`to`,
 *  AC-RPT-01/02) - not derived from the event log, given directly. */
const CURRENT_STATE: Record<
  string,
  { status: 'OPEN' | 'SNOOZED' | 'CLOSED'; assigneeId: string | null; lifecycleKey: string }
> = {
  C1: { status: 'CLOSED', assigneeId: null, lifecycleKey: 'new_lead' },
  C2: { status: 'CLOSED', assigneeId: null, lifecycleKey: 'new_lead' },
  C3: { status: 'OPEN', assigneeId: 'u_ann', lifecycleKey: 'new_lead' },
  C4: { status: 'CLOSED', assigneeId: null, lifecycleKey: 'new_lead' },
  C5: { status: 'CLOSED', assigneeId: null, lifecycleKey: 'hot_lead' },
  C6: { status: 'OPEN', assigneeId: null, lifecycleKey: 'hot_lead' },
  C7: { status: 'SNOOZED', assigneeId: null, lifecycleKey: 'payment' },
  C8: { status: 'CLOSED', assigneeId: null, lifecycleKey: 'customer' },
};

const LIFECYCLE_DEFS: { key: string; label: string; color: string; sortOrder: number }[] = [
  { key: 'new_lead', label: 'New Lead', color: '#3B82F6', sortOrder: 0 },
  { key: 'hot_lead', label: 'Hot Lead', color: '#F97316', sortOrder: 1 },
  { key: 'payment', label: 'Payment', color: '#A855F7', sortOrder: 2 },
  { key: 'customer', label: 'Customer', color: '#22C55E', sortOrder: 3 },
  { key: 'cold_lead', label: 'Cold Lead', color: '#64748B', sortOrder: 4 },
];

function contactName(contactId: string): string {
  return `Customer ${contactId.replace('C', '')}`;
}

// ---------------------------------------------------------------------------
// Timezone-aware bucketing (mirrors D-A9-8's shape: resolve edges from the
// zone, one pass over the events).
// ---------------------------------------------------------------------------

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** The UTC offset (ms, east-positive) `tz` observes at `date` - the standard
 *  two-step technique (format the instant in `tz`, diff against the same
 *  wall-clock digits read as UTC). Correct across DST because it reads the
 *  actual offset Intl applies at that instant. */
function tzOffsetMs(date: Date, tz: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  const asIfUtc = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'), get('second'));
  return asIfUtc - date.getTime();
}

/** The UTC instant of local `y-m-d hh:mm:ss` in `tz`. */
function zonedTimeToUtc(y: number, m: number, d: number, hh: number, tz: string): Date {
  const guess = new Date(Date.UTC(y, m - 1, d, hh, 0, 0));
  return new Date(guess.getTime() - tzOffsetMs(guess, tz));
}

function localParts(at: string, tz: string): { year: number; month: number; day: number; hour: number } {
  const date = new Date(at);
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour') };
}

function isoWeekKey(year: number, month: number, day: number): string {
  const d = new Date(Date.UTC(year, month - 1, day));
  const dayNum = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const weekNum =
    1 +
    Math.round(
      ((d.getTime() - firstThursday.getTime()) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7,
    );
  return `${d.getUTCFullYear()}-W${pad(weekNum)}`;
}

function bucketKeyOf(at: string, tz: string, granularity: ReportGranularity): string {
  const { year, month, day, hour } = localParts(at, tz);
  switch (granularity) {
    case 'hour':
      return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}`;
    case 'week':
      return isoWeekKey(year, month, day);
    case 'month':
      return `${year}-${pad(month)}`;
    case 'day':
    default:
      return `${year}-${pad(month)}-${pad(day)}`;
  }
}

function enumerateDayKeys(from: string, to: string): string[] {
  const [fy, fm, fd] = from.split('-').map(Number);
  const [ty, tm, td] = to.split('-').map(Number);
  const start = Date.UTC(fy, fm - 1, fd);
  const end = Date.UTC(ty, tm - 1, td);
  const keys: string[] = [];
  for (let t = start; t <= end; t += 86400000) {
    const d = new Date(t);
    keys.push(`${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`);
  }
  return keys;
}

export const MAX_MOCK_BUCKETS = 120;

export function autoGranularity(from: string, to: string): ReportGranularity {
  const days = enumerateDayKeys(from, to).length;
  if (days <= 2) return 'hour';
  if (days <= 62) return 'day';
  if (days <= 366) return 'week';
  return 'month';
}

/** Bucket edges for the range - day/hour enumerated exactly; week/month grouped
 *  from the day list (a reasonable mock simplification - the real S1 backend
 *  owns the authoritative `zoneinfo` edges per D-A9-8). */
export function enumerateBuckets(from: string, to: string, tz: string, granularity: ReportGranularity): ReportBucket[] {
  const days = enumerateDayKeys(from, to);
  const buckets: ReportBucket[] = [];

  if (granularity === 'hour') {
    for (const day of days) {
      const [y, m, d] = day.split('-').map(Number);
      for (let h = 0; h < 24; h++) {
        const startsAt = zonedTimeToUtc(y, m, d, h, tz);
        const endsAt = zonedTimeToUtc(y, m, d, h + 1, tz);
        buckets.push({ key: `${day}T${pad(h)}`, startsAt: startsAt.toISOString(), endsAt: endsAt.toISOString() });
        if (buckets.length >= MAX_MOCK_BUCKETS) return buckets;
      }
    }
    return buckets;
  }

  if (granularity === 'day') {
    for (const day of days) {
      const [y, m, d] = day.split('-').map(Number);
      const startsAt = zonedTimeToUtc(y, m, d, 0, tz);
      const endsAt = zonedTimeToUtc(y, m, d + 1, 0, tz);
      buckets.push({ key: day, startsAt: startsAt.toISOString(), endsAt: endsAt.toISOString() });
      if (buckets.length >= MAX_MOCK_BUCKETS) return buckets;
    }
    return buckets;
  }

  // week / month: group the day list by its bucket key, edges = the
  // enclosing group's first/last day boundaries.
  const seen = new Map<string, { first: string; last: string }>();
  for (const day of days) {
    const [y, m, d] = day.split('-').map(Number);
    const key = granularity === 'week' ? isoWeekKey(y, m, d) : `${y}-${pad(m)}`;
    const entry = seen.get(key);
    if (!entry) seen.set(key, { first: day, last: day });
    else entry.last = day;
  }
  for (const [key, { first, last }] of Array.from(seen)) {
    const [fy, fm, fd] = first.split('-').map(Number);
    const [ly, lm, ld] = last.split('-').map(Number);
    const startsAt = zonedTimeToUtc(fy, fm, fd, 0, tz);
    const endsAt = zonedTimeToUtc(ly, lm, ld + 1, 0, tz);
    buckets.push({ key, startsAt: startsAt.toISOString(), endsAt: endsAt.toISOString() });
    if (buckets.length >= MAX_MOCK_BUCKETS) break;
  }
  return buckets;
}

function withinHalfOpen(at: string, startIso: string, endIso: string): boolean {
  const t = new Date(at).getTime();
  return t >= new Date(startIso).getTime() && t < new Date(endIso).getTime();
}

function countPerBucket(events: { at: string }[], buckets: ReportBucket[], tz: string, granularity: ReportGranularity): number[] {
  const counts = new Map<string, number>(buckets.map((b) => [b.key, 0]));
  for (const e of events) {
    const key = bucketKeyOf(e.at, tz, granularity);
    if (counts.has(key)) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return buckets.map((b) => counts.get(b.key) ?? 0);
}

// ---------------------------------------------------------------------------
// Stats (mirrors report_stats.py - pure functions, D-A9-9).
// ---------------------------------------------------------------------------

function percentile(sorted: number[], p: number): number | null {
  const n = sorted.length;
  if (n === 0) return null;
  if (n === 1) return Math.round(sorted[0]);
  const i = p * (n - 1);
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return Math.round(sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo));
}

function statsOf(values: number[], derivedCount?: number): DurationStats {
  const sorted = [...values].sort((a, b) => a - b);
  return {
    medianSeconds: percentile(sorted, 0.5),
    p90Seconds: percentile(sorted, 0.9),
    averageSeconds: sorted.length ? Math.round(sorted.reduce((a, b) => a + b, 0) / sorted.length) : null,
    sampleCount: sorted.length,
    ...(derivedCount !== undefined ? { derivedFromMessages: derivedCount } : {}),
  };
}

// ---------------------------------------------------------------------------
// Filtering + samples.
// ---------------------------------------------------------------------------

function matchesUser(actorUserId: string | null | undefined, toValue: string | null | undefined, userId?: string | null): boolean {
  if (!userId) return true;
  return actorUserId === userId || toValue === userId;
}

interface WindowResult {
  buckets: ReportBucket[];
  granularity: ReportGranularity;
  windowStart: string;
  windowEnd: string;
}

function resolveWindow(filters: ReportFilters): WindowResult {
  const granularity = filters.granularity ?? autoGranularity(filters.from, filters.to);
  const buckets = enumerateBuckets(filters.from, filters.to, filters.tz, granularity);
  const windowStart = buckets[0]?.startsAt ?? zonedTimeToUtc(2026, 1, 1, 0, filters.tz).toISOString();
  const windowEnd = buckets[buckets.length - 1]?.endsAt ?? windowStart;
  return { buckets, granularity, windowStart, windowEnd };
}

interface ResponseSample {
  contactId: string;
  seconds: number;
  actorUserId: string | null;
  derived: boolean;
}

function computeResponseSamples(filters: ReportFilters, windowStart: string, windowEnd: string): ResponseSample[] {
  const samples: ResponseSample[] = [];
  const repliedContacts = new Set<string>();
  for (const e of FIXTURE_EVENTS) {
    if (e.type !== 'first_agent_reply') continue;
    repliedContacts.add(e.contactId);
    if (!withinHalfOpen(e.at, windowStart, windowEnd)) continue;
    if (!matchesUser(e.actorUserId, null, filters.userId)) continue;
    samples.push({ contactId: e.contactId, seconds: e.responseSeconds ?? 0, actorUserId: e.actorUserId ?? null, derived: false });
  }
  // D-A9-6: contacts with NO first_agent_reply event AT ALL derive from
  // messages - first AGENT row minus the latest CONTACT row strictly before
  // it. SYSTEM notes never count as a reply.
  const byContact = new Map<string, FixtureMessage[]>();
  for (const m of FIXTURE_MESSAGES) {
    if (!byContact.has(m.contactId)) byContact.set(m.contactId, []);
    byContact.get(m.contactId)!.push(m);
  }
  for (const [contactId, msgs] of Array.from(byContact)) {
    if (repliedContacts.has(contactId)) continue;
    const sorted = [...msgs].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
    const firstAgent = sorted.find((m) => m.sender === 'AGENT');
    if (!firstAgent) continue;
    if (!withinHalfOpen(firstAgent.at, windowStart, windowEnd)) continue;
    const priorContact = [...sorted]
      .filter((m) => m.sender === 'CONTACT' && new Date(m.at).getTime() < new Date(firstAgent.at).getTime())
      .pop();
    if (!priorContact) continue;
    if (!matchesUser(firstAgent.actorUserId, null, filters.userId)) continue;
    const seconds = Math.round((new Date(firstAgent.at).getTime() - new Date(priorContact.at).getTime()) / 1000);
    samples.push({ contactId, seconds, actorUserId: firstAgent.actorUserId ?? null, derived: true });
  }
  return samples;
}

interface ResolutionSample {
  contactId: string;
  seconds: number;
  actorUserId: string | null;
  closeReasonId: string | null;
}

function computeResolutionSamples(filters: ReportFilters, windowStart: string, windowEnd: string): ResolutionSample[] {
  const samples: ResolutionSample[] = [];
  for (const e of FIXTURE_EVENTS) {
    if (e.type !== 'closed') continue;
    if (!withinHalfOpen(e.at, windowStart, windowEnd)) continue;
    if (!matchesUser(e.actorUserId, null, filters.userId)) continue;
    const cycleStart = [...FIXTURE_EVENTS]
      .filter(
        (o) =>
          o.contactId === e.contactId &&
          (o.type === 'opened' || o.type === 'reopened') &&
          new Date(o.at).getTime() <= new Date(e.at).getTime(),
      )
      .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())[0];
    if (!cycleStart) continue;
    const seconds = Math.round((new Date(e.at).getTime() - new Date(cycleStart.at).getTime()) / 1000);
    samples.push({ contactId: e.contactId, seconds, actorUserId: e.actorUserId ?? null, closeReasonId: e.closeReasonId ?? null });
  }
  return samples;
}

// ---------------------------------------------------------------------------
// Dashboard.
// ---------------------------------------------------------------------------

function buildDashboard(filters: ReportFilters): DashboardResponse {
  const { buckets, granularity, windowStart, windowEnd } = resolveWindow(filters);

  const openedEvents = FIXTURE_EVENTS.filter(
    (e) => e.type === 'opened' && withinHalfOpen(e.at, windowStart, windowEnd) && matchesUser(e.actorUserId, null, filters.userId),
  );
  const closedEvents = FIXTURE_EVENTS.filter(
    (e) => e.type === 'closed' && withinHalfOpen(e.at, windowStart, windowEnd) && matchesUser(e.actorUserId, null, filters.userId),
  );

  const responseSamples = computeResponseSamples(filters, windowStart, windowEnd);
  const resolutionSamples = computeResolutionSamples(filters, windowStart, windowEnd);

  const contactEntries = Object.entries(CURRENT_STATE);
  const scopedContacts = filters.userId
    ? contactEntries.filter(([, s]) => s.assigneeId === filters.userId)
    : contactEntries;

  const tiles = {
    open: scopedContacts.filter(([, s]) => s.status === 'OPEN').length,
    snoozed: scopedContacts.filter(([, s]) => s.status === 'SNOOZED').length,
    assigned: contactEntries.filter(([, s]) => s.status !== 'CLOSED' && s.assigneeId).length,
    unassigned: contactEntries.filter(([, s]) => s.status !== 'CLOSED' && !s.assigneeId).length,
  };

  const totalContacts = contactEntries.length;
  const lifecycle: DashboardLifecycleStage[] = LIFECYCLE_DEFS.map((def, i) => {
    const count = contactEntries.filter(([, s]) => s.lifecycleKey === def.key).length;
    return {
      statusId: `status_${def.key}`,
      key: def.key,
      label: def.label,
      color: def.color,
      sortOrder: i,
      count,
      percent: totalContacts ? Math.round((count / totalContacts) * 1000) / 10 : 0,
    };
  });

  const closedByAgent = new Map<string, number>();
  for (const e of closedEvents) {
    if (!e.actorUserId) continue;
    closedByAgent.set(e.actorUserId, (closedByAgent.get(e.actorUserId) ?? 0) + 1);
  }
  const topAgents: DashboardTopAgent[] = Array.from(closedByAgent.entries())
    .map(([userId, closedCount]) => {
      const own = responseSamples.filter((s) => s.actorUserId === userId).map((s) => s.seconds).sort((a, b) => a - b);
      return { userId, name: USERS[userId] ?? '', closedCount, medianResponseSeconds: percentile(own, 0.5) };
    })
    .sort((a, b) => b.closedCount - a.closedCount || a.name.localeCompare(b.name));

  return {
    timezone: filters.tz,
    range: { from: filters.from, to: filters.to },
    granularity,
    buckets,
    tiles,
    lifecycle,
    series: {
      opened: countPerBucket(openedEvents, buckets, filters.tz, granularity),
      closed: countPerBucket(closedEvents, buckets, filters.tz, granularity),
    },
    responseTotals: statsOf(
      responseSamples.map((s) => s.seconds),
      responseSamples.filter((s) => s.derived).length,
    ),
    resolutionTotals: statsOf(resolutionSamples.map((s) => s.seconds)),
    topAgents,
  };
}

// ---------------------------------------------------------------------------
// Reports.
// ---------------------------------------------------------------------------

const REPORT_DESCRIPTORS: ReportDescriptor[] = [
  { key: 'conversations', label: 'Conversations', supportsGroupBy: [], paginated: false, exportable: true },
  { key: 'responses', label: 'Responses', supportsGroupBy: ['user'], paginated: false, exportable: true },
  { key: 'resolutions', label: 'Resolutions', supportsGroupBy: ['user'], paginated: false, exportable: true },
  { key: 'messages', label: 'Messages', supportsGroupBy: ['channel'], paginated: false, exportable: true },
  { key: 'users', label: 'Users', supportsGroupBy: [], paginated: true, exportable: true },
  { key: 'leaderboard', label: 'Leaderboard', supportsGroupBy: [], paginated: true, exportable: true },
  { key: 'assignments', label: 'Assignment log', supportsGroupBy: [], paginated: true, exportable: true },
];

const RESPONSE_BUCKET_DEFS: { bucket: string; label: string; lo: number; hi: number }[] = [
  { bucket: 'lt30s', label: '< 30s', lo: 0, hi: 30 },
  { bucket: '30s-2m', label: '30s - 2m', lo: 30, hi: 120 },
  { bucket: '2m-5m', label: '2m - 5m', lo: 120, hi: 300 },
  { bucket: '5m-10m', label: '5m - 10m', lo: 300, hi: 600 },
  { bucket: '10m-30m', label: '10m - 30m', lo: 600, hi: 1800 },
  { bucket: '30m-1h', label: '30m - 1h', lo: 1800, hi: 3600 },
  { bucket: 'gt1h', label: '> 1h', lo: 3600, hi: Infinity },
];

function pct(count: number, total: number): number {
  return total ? Math.round((count / total) * 1000) / 10 : 0;
}

function buildUserRows(filters: ReportFilters, windowStart: string, windowEnd: string): UserReportRow[] {
  const responseSamples = computeResponseSamples(filters, windowStart, windowEnd);
  const resolutionSamples = computeResolutionSamples(filters, windowStart, windowEnd);

  return Object.entries(USERS).map(([userId, name]) => {
    const assignedCount = FIXTURE_EVENTS.filter(
      (e) => e.type === 'assigned' && e.toValue === userId && withinHalfOpen(e.at, windowStart, windowEnd),
    ).length;
    const closedCount = FIXTURE_EVENTS.filter(
      (e) => e.type === 'closed' && e.actorUserId === userId && withinHalfOpen(e.at, windowStart, windowEnd),
    ).length;
    const ownMessages = FIXTURE_MESSAGES.filter(
      (m) => m.sender === 'AGENT' && m.actorUserId === userId && withinHalfOpen(m.at, windowStart, windowEnd),
    );
    const uniqueContacts = new Set(ownMessages.map((m) => m.contactId)).size;
    const commentsCount = FIXTURE_EVENTS.filter(
      (e) => e.type === 'comment_added' && e.actorUserId === userId && withinHalfOpen(e.at, windowStart, windowEnd),
    ).length;
    const ownResponses = responseSamples.filter((s) => s.actorUserId === userId).map((s) => s.seconds).sort((a, b) => a - b);
    const ownResolutions = resolutionSamples.filter((s) => s.actorUserId === userId).map((s) => s.seconds).sort((a, b) => a - b);

    return {
      userId,
      name,
      teamName: null,
      assignedCount,
      closedCount,
      uniqueContacts,
      messagesSent: ownMessages.length,
      commentsCount,
      medianFirstResponseSeconds: percentile(ownResponses, 0.5),
      medianResolutionSeconds: percentile(ownResolutions, 0.5),
    };
  });
}

function paginate<T>(rows: T[], page?: number, pageSize?: number): { rows: T[]; page: number; pageSize: number; total: number } {
  const size = Math.min(Math.max(pageSize ?? 25, 1), 200);
  const current = Math.max(page ?? 0, 0);
  return { rows: rows.slice(current * size, current * size + size), page: current, pageSize: size, total: rows.length };
}

function buildReport(reportKey: ReportKey, query: ReportQuery): ReportResponse {
  const { buckets, granularity, windowStart, windowEnd } = resolveWindow(query);
  const base = { timezone: query.tz, range: { from: query.from, to: query.to }, granularity, buckets };

  switch (reportKey) {
    case 'conversations': {
      const opened = FIXTURE_EVENTS.filter((e) => e.type === 'opened' && withinHalfOpen(e.at, windowStart, windowEnd));
      const closed = FIXTURE_EVENTS.filter((e) => e.type === 'closed' && withinHalfOpen(e.at, windowStart, windowEnd));
      const reopened = FIXTURE_EVENTS.filter((e) => e.type === 'reopened' && withinHalfOpen(e.at, windowStart, windowEnd));
      const series: ReportSeries[] = [
        { key: 'opened', label: 'Opened', points: countPerBucket(opened, buckets, query.tz, granularity) },
        { key: 'closed', label: 'Closed', points: countPerBucket(closed, buckets, query.tz, granularity) },
        { key: 'reopened', label: 'Reopened', points: countPerBucket(reopened, buckets, query.tz, granularity) },
      ];
      const totals: ConversationsReportTotals = { opened: opened.length, closed: closed.length, reopened: reopened.length };
      return { ...base, reportKey, series, rows: [], totals };
    }

    case 'responses': {
      const samples = computeResponseSamples(query, windowStart, windowEnd);
      const totals = statsOf(samples.map((s) => s.seconds), samples.filter((s) => s.derived).length);
      if (query.groupBy === 'user') {
        const rows: DurationByUserRow[] = Object.entries(USERS).map(([userId, name]) => {
          const own = samples.filter((s) => s.actorUserId === userId).map((s) => s.seconds).sort((a, b) => a - b);
          return {
            userId,
            name,
            sampleCount: own.length,
            medianSeconds: percentile(own, 0.5),
            p90Seconds: percentile(own, 0.9),
            averageSeconds: own.length ? Math.round(own.reduce((a, b) => a + b, 0) / own.length) : null,
          };
        });
        return { ...base, reportKey, series: [], rows, totals };
      }
      const rows: ResponseBucketRow[] = RESPONSE_BUCKET_DEFS.map((def) => {
        const count = samples.filter((s) => s.seconds >= def.lo && s.seconds < def.hi).length;
        return { bucket: def.bucket, label: def.label, count, percent: pct(count, samples.length) };
      });
      return { ...base, reportKey, series: [], rows, totals };
    }

    case 'resolutions': {
      const samples = computeResolutionSamples(query, windowStart, windowEnd);
      const totals = statsOf(samples.map((s) => s.seconds));
      if (query.groupBy === 'user') {
        const rows: DurationByUserRow[] = Object.entries(USERS).map(([userId, name]) => {
          const own = samples.filter((s) => s.actorUserId === userId).map((s) => s.seconds).sort((a, b) => a - b);
          return {
            userId,
            name,
            sampleCount: own.length,
            medianSeconds: percentile(own, 0.5),
            p90Seconds: percentile(own, 0.9),
            averageSeconds: own.length ? Math.round(own.reduce((a, b) => a + b, 0) / own.length) : null,
          };
        });
        return { ...base, reportKey, series: [], rows, totals };
      }
      const byReason = new Map<string, number>();
      for (const s of samples) {
        const key = s.closeReasonId ?? '';
        byReason.set(key, (byReason.get(key) ?? 0) + 1);
      }
      const rows: CloseReasonRow[] = Array.from(byReason.entries()).map(([id, count]) => ({
        closeReasonId: id || null,
        name: id ? (CLOSE_REASONS[id] ?? null) : null,
        count,
        percent: pct(count, samples.length),
      }));
      return { ...base, reportKey, series: [], rows, totals };
    }

    case 'messages': {
      const inWindow = FIXTURE_MESSAGES.filter(
        (m) => withinHalfOpen(m.at, windowStart, windowEnd) && (!query.channelId || m.channelId === query.channelId),
      );
      const incoming = inWindow.filter((m) => m.sender === 'CONTACT');
      const outgoing = inWindow.filter((m) => m.sender === 'AGENT');
      const series: ReportSeries[] = [
        { key: 'incoming', label: 'Incoming', points: countPerBucket(incoming, buckets, query.tz, granularity) },
        { key: 'outgoing', label: 'Outgoing', points: countPerBucket(outgoing, buckets, query.tz, granularity) },
      ];
      const totals: MessagesReportTotals = { incoming: incoming.length, outgoing: outgoing.length };
      if (query.groupBy === 'channel') {
        const rows: MessageChannelRow[] = [
          { channelId: CHANNEL.id, name: CHANNEL.name, channelType: CHANNEL.channelType, incoming: incoming.length, outgoing: outgoing.length },
        ];
        return { ...base, reportKey, series, rows, totals };
      }
      return { ...base, reportKey, series, rows: [], totals };
    }

    case 'users': {
      const allRows = buildUserRows(query, windowStart, windowEnd);
      const { rows, page, pageSize, total } = paginate(allRows, query.page, query.pageSize);
      const totals: UsersReportTotals = { userCount: allRows.length };
      return { ...base, reportKey, series: [], rows, totals, page, pageSize, total };
    }

    case 'leaderboard': {
      const allRows = buildUserRows(query, windowStart, windowEnd)
        .sort(
          (a, b) =>
            b.closedCount - a.closedCount ||
            (a.medianFirstResponseSeconds ?? Infinity) - (b.medianFirstResponseSeconds ?? Infinity) ||
            a.name.localeCompare(b.name),
        )
        .map((row, i) => ({ ...row, rank: i + 1 }) satisfies LeaderboardRow);
      const { rows, page, pageSize, total } = paginate(allRows, query.page, query.pageSize);
      const totals: UsersReportTotals = { userCount: allRows.length };
      return { ...base, reportKey, series: [], rows, totals, page, pageSize, total };
    }

    case 'assignments': {
      const assigned = FIXTURE_EVENTS.filter((e) => e.type === 'assigned' && withinHalfOpen(e.at, windowStart, windowEnd));
      const unassigned = FIXTURE_EVENTS.filter((e) => e.type === 'unassigned' && withinHalfOpen(e.at, windowStart, windowEnd));
      const series: ReportSeries[] = [{ key: 'assigned', label: 'Assigned', points: countPerBucket(assigned, buckets, query.tz, granularity) }];
      const allRows: AssignmentLogRow[] = [...assigned, ...unassigned]
        .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime() || b.id.localeCompare(a.id))
        .map((e) => ({
          id: e.id,
          createdAt: e.at,
          contactId: e.contactId,
          contactName: contactName(e.contactId),
          eventType: e.type as 'assigned' | 'unassigned',
          previousAssigneeId: e.fromValue ?? null,
          previousAssigneeName: e.fromValue ? (USERS[e.fromValue] ?? null) : null,
          assignedToId: e.toValue ?? null,
          assignedToName: e.toValue ? (USERS[e.toValue] ?? null) : null,
          source: 'agent',
          actorUserId: e.actorUserId ?? null,
          actorName: e.actorUserId ? (USERS[e.actorUserId] ?? null) : null,
        }));
      const { rows, page, pageSize, total } = paginate(allRows, query.page, query.pageSize);
      const totals: AssignmentsReportTotals = { assigned: assigned.length, unassigned: unassigned.length };
      return { ...base, reportKey, series, rows, totals, page, pageSize, total };
    }

    default:
      return { ...base, reportKey, series: [], rows: [], totals: {} };
  }
}

// ---------------------------------------------------------------------------
// Export - mirrors ContactService.exportContacts (plan 26): a bounded
// selection resolves inside the wait window, an unfiltered "everything"
// export demonstrates the Jobs-drawer fallback (never a silent failure).
// ---------------------------------------------------------------------------

function csvColumns(reportKey: ReportKey): { key: string; label: string }[] {
  switch (reportKey) {
    case 'assignments':
      return [
        { key: 'createdAt', label: 'Created At' },
        { key: 'contactName', label: 'Contact' },
        { key: 'eventType', label: 'Event' },
        { key: 'previousAssigneeName', label: 'Previous Assignee' },
        { key: 'assignedToName', label: 'Assigned To' },
        { key: 'source', label: 'Source' },
        { key: 'actorName', label: 'Actor' },
      ];
    case 'users':
    case 'leaderboard':
      return [
        { key: 'name', label: 'Name' },
        { key: 'assignedCount', label: 'Assigned' },
        { key: 'closedCount', label: 'Closed' },
        { key: 'uniqueContacts', label: 'Unique Contacts' },
        { key: 'messagesSent', label: 'Messages Sent' },
        { key: 'commentsCount', label: 'Comments' },
        { key: 'medianFirstResponseSeconds', label: 'Median First Response (s)' },
        { key: 'medianResolutionSeconds', label: 'Median Resolution (s)' },
      ];
    case 'resolutions':
      return [
        { key: 'name', label: 'Close Reason' },
        { key: 'count', label: 'Count' },
        { key: 'percent', label: 'Percent' },
      ];
    case 'responses':
      return [
        { key: 'label', label: 'Response Time' },
        { key: 'count', label: 'Count' },
        { key: 'percent', label: 'Percent' },
      ];
    case 'messages':
      return [
        { key: 'name', label: 'Channel' },
        { key: 'incoming', label: 'Incoming' },
        { key: 'outgoing', label: 'Outgoing' },
      ];
    case 'conversations':
    default:
      return [
        { key: 'key', label: 'Bucket' },
        { key: 'opened', label: 'Opened' },
        { key: 'closed', label: 'Closed' },
        { key: 'reopened', label: 'Reopened' },
      ];
  }
}

function reportRowsForExport(reportKey: ReportKey, filters: ReportFilters): Record<string, unknown>[] {
  const response = buildReport(reportKey, { ...filters, pageSize: 200 });
  if (reportKey === 'conversations') {
    return response.buckets.map((b, i) => ({
      key: b.key,
      opened: response.series.find((s) => s.key === 'opened')?.points[i] ?? 0,
      closed: response.series.find((s) => s.key === 'closed')?.points[i] ?? 0,
      reopened: response.series.find((s) => s.key === 'reopened')?.points[i] ?? 0,
    }));
  }
  return response.rows as Record<string, unknown>[];
}

export const mockOmnichannelReportService: OmnichannelReportService = {
  meta() {
    return delay<ReportMeta>({
      reports: REPORT_DESCRIPTORS,
      granularities: ['hour', 'day', 'week', 'month'],
      dimensions: { team: { available: false } },
    });
  },

  dashboard(_workspaceId, filters) {
    return delay(buildDashboard(filters));
  },

  report(_workspaceId, reportKey, query) {
    return delay(buildReport(reportKey, query));
  },

  async exportReport(_workspaceId, reportKey, filters: ReportExportRequest) {
    const rows = reportRowsForExport(reportKey, filters);
    const columns = csvColumns(reportKey);

    // An unfiltered ("everything") export on a report with a lot of rows
    // demonstrates the wait-window -> Jobs fallback (D-A9-4's async job
    // shape); a bounded/filtered query resolves inside the window.
    if (!filters.userId && !filters.channelId && rows.length > 5) {
      await delay(undefined, 1400);
      throw new ExportPendingError('The export is still running - it will finish in Jobs.', `job-mock-${Date.now()}`);
    }

    await delay(undefined, 300);
    return toCsv(
      columns.map((c) => c.label),
      rows.map((row) => columns.map((c) => row[c.key] as string | number | null | undefined)),
    );
  },
};
