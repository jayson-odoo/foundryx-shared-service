import type { NumberCatalogItem } from '@/types/numbering';

/** Numbering catalog rows for the slice W4-SETTINGS tests. */
export const NUMBERS_FIXTURE: NumberCatalogItem[] = [
  {
    docType: 'invoice',
    label: 'Invoice',
    module: 'core',
    defaultPrefix: 'INV-',
    defaultFormat: '{prefix}{YYYY}-{NNNN}',
    defaultReset: 'yearly',
    overridePrefix: null,
    overrideFormat: null,
    overrideReset: null,
    prefix: 'INV-',
    formatPattern: '{prefix}{YYYY}-{NNNN}',
    reset: 'yearly',
    nextVal: 42,
    sample: 'INV-2026-0042',
  },
  {
    docType: 'quotation',
    label: 'Quotation',
    module: 'core',
    defaultPrefix: 'QT-',
    defaultFormat: '{prefix}{NNNNN}',
    defaultReset: 'never',
    overridePrefix: 'Q-',
    overrideFormat: null,
    overrideReset: null,
    prefix: 'Q-',
    formatPattern: '{prefix}{NNNNN}',
    reset: 'never',
    nextVal: 7,
    sample: 'Q-00007',
  },
];
