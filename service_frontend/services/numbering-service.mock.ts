/** Mock numbering service — static catalog + simulated latency (unit tests). */
import type { NumberCatalogItem, NumberFormatSet, NumberReset } from '@/types/numbering';
import type { NumberingService } from './numbering-service';

interface Override {
  prefix: string;
  formatPattern: string;
  reset: NumberReset;
}

const BASE: Omit<NumberCatalogItem, 'overridePrefix' | 'overrideFormat' | 'overrideReset' | 'prefix' | 'formatPattern' | 'reset' | 'nextVal' | 'sample'>[] = [
  { docType: 'document_no', label: 'Document number', module: 'core', defaultPrefix: 'DOC-', defaultFormat: '{prefix}{YYYY}-{NNNN}', defaultReset: 'yearly' },
  { docType: 'invoice', label: 'Invoice', module: 'finance', defaultPrefix: 'INV-', defaultFormat: '{prefix}{YYYY}-{NNNNN}', defaultReset: 'yearly' },
  { docType: 'quotation', label: 'Quotation', module: 'crm', defaultPrefix: 'QUO-', defaultFormat: '{prefix}{YYYY}-{NNNNN}', defaultReset: 'yearly' },
];

const overrides = new Map<string, Override>();
const nextVals = new Map<string, number>();
const delay = <T>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 60));

function sampleOf(prefix: string, pattern: string, seq: number): string {
  const year = new Date().getFullYear();
  return pattern
    .replace(/\{prefix\}/g, prefix)
    .replace(/\{YYYY\}/g, String(year))
    .replace(/\{YY\}/g, String(year).slice(-2))
    .replace(/\{MM\}/g, String(new Date().getMonth() + 1).padStart(2, '0'))
    .replace(/\{DD\}/g, String(new Date().getDate()).padStart(2, '0'))
    .replace(/\{(N+)\}/g, (_m, n: string) => String(seq).padStart(n.length, '0'));
}

export const mockNumberingService: NumberingService = {
  getCatalog() {
    return delay(
      BASE.map((b): NumberCatalogItem => {
        const ov = overrides.get(b.docType);
        const prefix = ov?.prefix ?? b.defaultPrefix;
        const formatPattern = ov?.formatPattern ?? b.defaultFormat;
        const reset = ov?.reset ?? b.defaultReset;
        const nextVal = nextVals.get(b.docType) ?? 1;
        return {
          ...b,
          overridePrefix: ov?.prefix ?? null,
          overrideFormat: ov?.formatPattern ?? null,
          overrideReset: ov?.reset ?? null,
          prefix,
          formatPattern,
          reset,
          nextVal,
          sample: sampleOf(prefix, formatPattern, nextVal),
        };
      }),
    );
  },
  setFormat(docType: string, body: NumberFormatSet) {
    overrides.set(docType, { ...body });
    return delay(undefined);
  },
  setNextVal(docType: string, nextVal: number) {
    nextVals.set(docType, nextVal);
    return delay(undefined);
  },
  resetFormat(docType: string) {
    overrides.delete(docType);
    return delay(undefined);
  },
};
