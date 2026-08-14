/** Mock terminology service (Phase A) - static map + simulated latency. */
import type { TermCatalogItem, TermLabels, TerminologyMap } from '@/types/terminology';
import type { TerminologyService } from './terminology-service';

const CATALOG: TermCatalogItem[] = [
  ['form', 'Form', 'Forms', 'Engines'],
  ['workflow', 'Workflow', 'Workflows', 'Engines'],
  ['template', 'Template', 'Templates', 'Engines'],
  ['document', 'Document', 'Documents', 'Content'],
  ['connection', 'Integration', 'Integrations', 'Settings'],
  ['role', 'Role', 'Roles', 'Access'],
  ['import', 'Import', 'Imports', 'Engines'],
].map(([key, s, p, group]) => ({
  key,
  module: 'core',
  group,
  description: null,
  defaultSingular: s,
  defaultPlural: p,
  overrideSingular: null,
  overridePlural: null,
  singular: s,
  plural: p,
}));

const overrides = new Map<string, TermLabels>();
const delay = <T>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 120));

export const mockTerminologyService: TerminologyService = {
  getTerminology() {
    const map: TerminologyMap = {};
    for (const item of CATALOG) {
      const ov = overrides.get(item.key);
      map[item.key] = ov ?? { singular: item.defaultSingular, plural: item.defaultPlural };
    }
    return delay(map);
  },
  getCatalog() {
    return delay(
      CATALOG.map((c) => {
        const ov = overrides.get(c.key);
        return {
          ...c,
          overrideSingular: ov?.singular ?? null,
          overridePlural: ov?.plural ?? null,
          singular: ov?.singular ?? c.defaultSingular,
          plural: ov?.plural ?? c.defaultPlural,
        };
      }),
    );
  },
  setTerm(key, labels) {
    overrides.set(key, labels);
    return delay(labels);
  },
  resetTerm(key) {
    overrides.delete(key);
    return delay(undefined);
  },
};
