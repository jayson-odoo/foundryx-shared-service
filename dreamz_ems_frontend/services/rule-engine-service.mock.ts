/**
 * Mock rule-engine service (Phase A). Mirrors what the backend will return:
 * `GET /rule-facts?sources=` from the whitelist fact registry (D7/D8 — thin
 * v1 set: `actor` + `record:tenant`) and `GET /rules` from the rule-site
 * registry (D12). Phase B swaps the binding in rule-engine-service.ts.
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type { RuleFact, RuleSiteRow } from '@/types/rules';
import { delay } from './mock-query';
import type { RuleEngineService } from './rule-engine-service';

const ACTOR_FACTS: RuleFact[] = [
  {
    key: 'actor.email',
    label: 'Email',
    type: 'string',
    source: 'actor',
    sourceLabel: 'Acting user',
  },
  {
    key: 'actor.name',
    label: 'Name',
    type: 'string',
    source: 'actor',
    sourceLabel: 'Acting user',
  },
  {
    key: 'actor.status',
    label: 'Status',
    type: 'enum',
    source: 'actor',
    sourceLabel: 'Acting user',
    options: [
      { value: 'active', label: 'Active' },
      { value: 'inactive', label: 'Inactive' },
    ],
  },
  {
    key: 'actor.roles',
    label: 'Roles',
    type: 'list',
    source: 'actor',
    sourceLabel: 'Acting user',
    options: [
      { value: 'admin', label: 'Admin' },
      { value: 'manager', label: 'Manager' },
      { value: 'agent', label: 'Agent' },
      { value: 'viewer', label: 'Viewer' },
    ],
  },
  {
    key: 'actor.createdAt',
    label: 'Member since',
    type: 'date',
    source: 'actor',
    sourceLabel: 'Acting user',
  },
];

const TENANT_RECORD_FACTS: RuleFact[] = [
  {
    key: 'record.name',
    label: 'Name',
    type: 'string',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
  {
    key: 'record.slug',
    label: 'Slug',
    type: 'string',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
  {
    key: 'record.isPlatform',
    label: 'Is platform',
    type: 'boolean',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
  {
    key: 'record.createdAt',
    label: 'Created at',
    type: 'date',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
  {
    key: 'record.userCount',
    label: 'User count',
    type: 'number',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
];

const FACTS_BY_SOURCE: Record<string, RuleFact[]> = {
  actor: ACTOR_FACTS,
  'record:tenant': TENANT_RECORD_FACTS,
};

/** Unknown `record:<entity>` sources fall back to the tenant shape so the
 * builder works on any status-engine entity during Phase A. */
function factsForSource(source: string): RuleFact[] {
  if (FACTS_BY_SOURCE[source]) return FACTS_BY_SOURCE[source];
  if (source.startsWith('record:')) {
    const entity = source.slice('record:'.length);
    return TENANT_RECORD_FACTS.map((f) => ({
      ...f,
      source,
      sourceLabel: `${entity.charAt(0).toUpperCase()}${entity.slice(1)} record`,
    }));
  }
  return [];
}

const MOCK_RULES: RuleSiteRow[] = [
  {
    site: 'status_transition',
    siteLabel: 'Status transition',
    context: 'Tenant · Active → Suspended',
    summary:
      'Acting user roles contains any of Admin AND Tenant record Is platform is no',
    target: 'tenant',
    updatedAt: '2026-06-01T09:30:00Z',
  },
  {
    site: 'status_transition',
    siteLabel: 'Status transition',
    context: 'Tenant · Suspended → Active',
    summary:
      'Tenant record Created at before 2026-01-01 OR (Acting user Email contains @dreamz.com AND Tenant record User count ≥ 5)',
    target: 'tenant',
    updatedAt: '2026-05-28T14:05:00Z',
  },
  {
    site: 'status_transition',
    siteLabel: 'Status transition',
    context: 'Ticket · Open → Resolved',
    summary: 'Acting user Status is Active',
    target: 'ticket',
    updatedAt: '2026-05-20T11:12:00Z',
  },
];

function applyQuery(
  rows: RuleSiteRow[],
  query: ListQuery,
): ListResult<RuleSiteRow> {
  let data = rows;
  const term = query.search?.trim().toLowerCase();
  if (term) {
    data = data.filter(
      (r) =>
        r.context.toLowerCase().includes(term) ||
        r.summary.toLowerCase().includes(term) ||
        r.siteLabel.toLowerCase().includes(term),
    );
  }
  const sortField = query.sort?.id ?? 'context';
  const dir = query.sort?.desc ? -1 : 1;
  data = [...data].sort((a, b) => {
    const value = (row: RuleSiteRow) => {
      switch (sortField) {
        case 'site':
          return row.siteLabel;
        case 'updated':
          return row.updatedAt ?? '';
        default:
          return row.context;
      }
    };
    return String(value(a)).localeCompare(String(value(b))) * dir;
  });
  const start = query.page * query.pageSize;
  return {
    data: data.slice(start, start + query.pageSize),
    total: data.length,
    page: query.page,
  };
}

export const mockRuleEngineService: RuleEngineService = {
  async getFacts(sources) {
    return delay(sources.flatMap(factsForSource), 150);
  },
  async listRules(query) {
    return delay(applyQuery(MOCK_RULES, query), 200);
  },
};
