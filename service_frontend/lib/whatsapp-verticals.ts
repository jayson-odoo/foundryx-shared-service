/**
 * Meta WhatsApp Business Profile `vertical` enum - mirror of the backend
 * `modules/omnichannel/verticals.py`. Drives the Profile-tab SearchSelect and
 * the client-side whitelist. Keep both lists in sync (plan 06 §2).
 */
export const WHATSAPP_VERTICALS = [
  'UNDEFINED',
  'OTHER',
  'AUTO',
  'BEAUTY',
  'APPAREL',
  'EDU',
  'ENTERTAIN',
  'EVENT_PLAN',
  'FINANCE',
  'GROCERY',
  'GOVT',
  'HOTEL',
  'HEALTH',
  'NONPROFIT',
  'PROF_SERVICES',
  'RETAIL',
  'TRAVEL',
  'RESTAURANT',
  'ALCOHOL',
  'ONLINE_GAMBLING',
  'PHYSICAL_GAMBLING',
  'OTC_DRUGS',
] as const;

export type WhatsAppVertical = (typeof WHATSAPP_VERTICALS)[number];

/** Friendly labels for the SearchSelect (value stays the Meta enum key). */
export const WHATSAPP_VERTICAL_LABELS: Record<WhatsAppVertical, string> = {
  UNDEFINED: 'Not set',
  OTHER: 'Other',
  AUTO: 'Automotive',
  BEAUTY: 'Beauty, Spa & Salon',
  APPAREL: 'Clothing & Apparel',
  EDU: 'Education',
  ENTERTAIN: 'Entertainment',
  EVENT_PLAN: 'Event Planning & Service',
  FINANCE: 'Finance & Banking',
  GROCERY: 'Food & Grocery',
  GOVT: 'Public Service',
  HOTEL: 'Hotel & Lodging',
  HEALTH: 'Medical & Health',
  NONPROFIT: 'Non-profit',
  PROF_SERVICES: 'Professional Services',
  RETAIL: 'Shopping & Retail',
  TRAVEL: 'Travel & Transportation',
  RESTAURANT: 'Restaurant',
  ALCOHOL: 'Alcohol',
  ONLINE_GAMBLING: 'Online Gambling & Gaming',
  PHYSICAL_GAMBLING: 'Physical Gambling & Gaming',
  OTC_DRUGS: 'Over-the-Counter Drugs',
};

export const WHATSAPP_VERTICAL_SET = new Set<string>(WHATSAPP_VERTICALS);

export const WHATSAPP_VERTICAL_OPTIONS = WHATSAPP_VERTICALS.map((v) => ({
  value: v,
  label: WHATSAPP_VERTICAL_LABELS[v],
}));
