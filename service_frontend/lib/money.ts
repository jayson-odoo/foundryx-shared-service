/** Money formatting (sprint-4/08). ONE formatter - uses Intl.NumberFormat for the
 * correct symbol + grouping + per-currency decimal places. Effective currency =
 * the value's own currency ?? the tenant default. Never render a bare price. */

/** Common ISO-4217 currencies for the pickers (any code is accepted server-side). */
export const CURRENCY_CODES = [
  'USD', 'EUR', 'GBP', 'MYR', 'SGD', 'AUD', 'CAD', 'JPY', 'CNY', 'HKD',
  'INR', 'IDR', 'THB', 'PHP', 'VND', 'KRW', 'AED', 'SAR', 'CHF', 'NZD',
];
export const CURRENCY_OPTIONS = CURRENCY_CODES.map((c) => ({ value: c, label: c }));

export function formatMoney(
  amount: number | null | undefined,
  currency?: string | null,
  decimals?: number | null,
): string {
  if (amount === null || amount === undefined) return '-';
  const cur = (currency || 'USD').toUpperCase();
  const opts: Intl.NumberFormatOptions = { style: 'currency', currency: cur };
  if (decimals !== null && decimals !== undefined) {
    opts.minimumFractionDigits = decimals;
    opts.maximumFractionDigits = decimals;
  }
  try {
    return new Intl.NumberFormat(undefined, opts).format(amount);
  } catch {
    // Unknown/invalid ISO code → fall back to "<CODE> <amount>".
    return `${cur} ${amount.toFixed(decimals ?? 2)}`;
  }
}

/* ───────────── Foundryx UIUX switch: money (playbook-uiux.md) ─────────────
 * New functions only; `formatMoney` above is untouched. Every amount shows
 * its currency before it, never a bare number: "RM" for the home currency,
 * the ISO code for every other ("SGD 14,000.00"), whatever the tenant default
 * (owner's choice, gap audit 10). Decimals follow the currency (JPY none).
 */

/** The one currency written with its local sign. Change here to change it. */
export const FX_HOME_CURRENCY = 'MYR';
const FX_HOME_SIGN = 'RM';

/** What stands before an amount: "RM" for the home currency, else the ISO code. */
export function fxCurrencyLabel(currency?: string | null): string {
  const cur = (currency || FX_HOME_CURRENCY).toUpperCase();
  return cur === FX_HOME_CURRENCY ? FX_HOME_SIGN : cur;
}

/** The currency's own number of decimals (JPY 0, most 2); 2 when unknown. */
export function fxCurrencyDecimals(currency?: string | null): number {
  try {
    return (
      new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: (currency || FX_HOME_CURRENCY).toUpperCase(),
      }).resolvedOptions().maximumFractionDigits ?? 2
    );
  } catch {
    return 2;
  }
}

/** "14,000.00": grouped, fixed decimals, no currency (the money field's text). */
export function formatFxAmount(amount: number, decimals = 2): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(amount);
}

/** "RM 14,000.00", "SGD 14,000.00", "JPY 14,000", "-RM 12.00"; null = "-". */
export function formatMoneyFx(
  amount: number | null | undefined,
  currency?: string | null,
  decimals?: number | null,
): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return '-';
  const places = decimals ?? fxCurrencyDecimals(currency);
  const text = `${fxCurrencyLabel(currency)} ${formatFxAmount(Math.abs(amount), places)}`;
  return amount < 0 && Number(formatFxAmount(Math.abs(amount), places).replace(/,/g, '')) !== 0
    ? `-${text}`
    : text;
}

/**
 * Reads a typed amount ("14000", "14,000", "14,000.5", "RM 14,000", "-12"),
 * or null when it is not an amount. Grouping commas must sit in threes.
 */
export function parseMoneyInput(text: string): number | null {
  const cleaned = text.trim().replace(/^[A-Za-z]{2,3}\s*/, '').replace(/\s+/g, '');
  if (!cleaned) return null;
  if (!/^-?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?$/.test(cleaned) || /^-?\.?$/.test(cleaned)) return null;
  const value = Number(cleaned.replace(/,/g, ''));
  return Number.isFinite(value) ? value : null;
}
