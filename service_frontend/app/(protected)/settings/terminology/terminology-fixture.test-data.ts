import type { TermCatalogItem } from '@/types/terminology';

/** Terminology catalog rows for the slice W4-SETTINGS tests. */
export const TERMS_FIXTURE: TermCatalogItem[] = [
  {
    key: 'contact',
    module: 'omnichannel',
    group: 'Omnichannel',
    description: null,
    defaultSingular: 'Contact',
    defaultPlural: 'Contacts',
    overrideSingular: null,
    overridePlural: null,
    singular: 'Contact',
    plural: 'Contacts',
  },
  {
    key: 'product',
    module: 'core',
    group: 'Catalog',
    description: null,
    defaultSingular: 'Product',
    defaultPlural: 'Products',
    overrideSingular: 'Item',
    overridePlural: 'Items',
    singular: 'Item',
    plural: 'Items',
  },
  {
    key: 'user',
    module: 'core',
    group: 'Access',
    description: null,
    defaultSingular: 'User',
    defaultPlural: 'Users',
    overrideSingular: null,
    overridePlural: null,
    singular: 'User',
    plural: 'Users',
  },
];
