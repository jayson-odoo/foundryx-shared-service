/**
 * The words Foundryx UIUX lists use for counts (playbook 0.71.0 "Lists"), kept
 * pure so page slices and tests share them.
 */

/** 1240 -> "1,240". */
export function fxCount(n: number): string {
  return n.toLocaleString('en-US');
}

/** "1 row" / "12 rows". */
export function fxRows(n: number): string {
  return `${fxCount(n)} ${n === 1 ? 'row' : 'rows'}`;
}

/** What an export covers: "12 ticked rows" or "All 1,240 matching rows". */
export function fxExportScope(ticked: number, total: number): string {
  if (ticked > 0) return `${fxCount(ticked)} ticked ${ticked === 1 ? 'row' : 'rows'}`;
  return `All ${fxCount(total)} matching ${total === 1 ? 'row' : 'rows'}`;
}

/** The export button names the count: "Export 1,240 rows". */
export function fxExportLabel(ticked: number, total: number): string {
  return `Export ${fxRows(ticked > 0 ? ticked : total)}`;
}

/** "3 selected". */
export function fxSelectedText(n: number): string {
  return `${fxCount(n)} selected`;
}

/**
 * A bulk update's action names how many rows it changes ("Update 12
 * products"), for the page-local bulk panels the page slices restyle.
 */
export function fxBulkUpdateLabel(n: number, nounMany: string, nounOne = nounMany): string {
  return `Update ${fxCount(n)} ${n === 1 ? nounOne : nounMany}`;
}
