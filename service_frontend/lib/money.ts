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
