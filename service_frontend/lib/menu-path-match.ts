/**
 * Which menu entry is the user actually on (ported from Sorento, AC-DLA-72).
 *
 * Two rules, and both exist because of a real wrong answer:
 *
 * 1. A prefix has to stop on a segment boundary. `pathname.startsWith(path)` also matched a
 *    sibling whose name merely begins with the same letters, so `/scm-archive` lit up `/scm`.
 *
 * 2. The most specific entry wins. A section landing page is a prefix of every page in its
 *    section, so `/scm` (Supply Chain -> Dashboard) stayed highlighted on Sales Orders, Reorder
 *    Planning and every other SCM page. Two entries highlighted at once is worse than none:
 *    the sidebar is how the user knows where they are.
 *
 * Rule 2 is decided against the VISIBLE menu, not against the route table. An entry the user
 * cannot see (no permission, module off) must not suppress one they can, or a page would show
 * no highlight at all.
 */
import type { MenuConfig, MenuItem } from '@/config/types';

/** Is `pathname` at, or inside, `path`? */
export function isUnderPath(path: string, pathname: string): boolean {
  if (path === pathname) return true;
  if (path.length <= 1) return false;
  return pathname.startsWith(`${path.replace(/\/$/, '')}/`);
}

/** Every path the given menu can highlight, including group nodes that carry one. */
export function collectMenuPaths(items: MenuConfig): string[] {
  const paths: string[] = [];
  const walk = (nodes: MenuConfig): void => {
    for (const item of nodes as MenuItem[]) {
      if (item.path) paths.push(item.path);
      if (item.children?.length) walk(item.children);
    }
  };
  walk(items);
  return paths;
}

/**
 * `path` is the entry to highlight for `pathname`, unless a more specific entry in the same
 * menu also matches - that one owns the highlight.
 */
export function matchesMenuPath(
  path: string,
  pathname: string,
  menuPaths: readonly string[],
): boolean {
  if (path === pathname) return true;
  if (!isUnderPath(path, pathname)) return false;
  const prefix = `${path.replace(/\/$/, '')}/`;
  return !menuPaths.some(
    (other) => other !== path && other.startsWith(prefix) && isUnderPath(other, pathname),
  );
}
