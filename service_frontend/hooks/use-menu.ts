import { MenuItem } from '@/config/types';
import { matchesMenuPath } from '@/lib/menu-path-match';

type MenuConfig = MenuItem[];

interface UseMenuReturn {
  /**
   * `menuPaths` is optional (fix round 1, AC-DLA-72 same-class defect):
   * pass `collectMenuPaths(visibleMenu)` for the segment-boundary +
   * most-specific-wins match (`lib/menu-path-match.ts`) - a naive
   * `startsWith` lit `/scm` up on `/scm-archive` and kept a section root lit
   * beside its own active child. Omitting it keeps the old plain-prefix
   * behaviour for callers that don't have a menu list at hand.
   */
  isActive: (path: string | undefined, menuPaths?: readonly string[]) => boolean;
  hasActiveChild: (children: MenuItem[] | undefined) => boolean;
  isItemActive: (item: MenuItem) => boolean;
  getCurrentItem: (items: MenuConfig) => MenuItem | undefined;
  getBreadcrumb: (items: MenuConfig) => MenuItem[];
  getChildren: (items: MenuConfig, level: number) => MenuConfig | null;
}

export const useMenu = (pathname: string): UseMenuReturn => {
  const isActive = (path: string | undefined, menuPaths?: readonly string[]): boolean => {
    if (!path) return false;
    if (menuPaths) {
      return matchesMenuPath(path, pathname, menuPaths);
    }
    if (path === '/') {
      return path === pathname;
    }
    return pathname.startsWith(path);
  };

  const hasActiveChild = (children: MenuItem[] | undefined): boolean => {
    if (!children || !Array.isArray(children)) return false;
    return children.some(
      (child: MenuItem) =>
        (child.path && isActive(child.path)) ||
        (child.children && hasActiveChild(child.children)),
    );
  };

  const isItemActive = (item: MenuItem): boolean => {
    return (
      (item.path ? isActive(item.path) : false) ||
      (item.children ? hasActiveChild(item.children) : false)
    );
  };

  /**
   * Every item (at any depth) whose own `path` is active for the current
   * pathname, paired with its ancestor chain. `isActive` is a `startsWith`
   * match, so a short SIBLING path (e.g. `/documents`) is "active" on a
   * longer sibling's route (`/documents/settings`) too - both land in this
   * list; `bestMatch` below is what actually disambiguates them.
   */
  const collectMatches = (
    items: MenuConfig,
    breadcrumb: MenuItem[] = [],
  ): { item: MenuItem; breadcrumb: MenuItem[] }[] => {
    const matches: { item: MenuItem; breadcrumb: MenuItem[] }[] = [];
    for (const item of items) {
      const currentBreadcrumb = [...breadcrumb, item];
      if (item.path && isActive(item.path)) {
        matches.push({ item, breadcrumb: currentBreadcrumb });
      }
      if (item.children && item.children.length > 0) {
        matches.push(...collectMatches(item.children, currentBreadcrumb));
      }
    }
    return matches;
  };

  /**
   * The LONGEST matching path wins (exact match first, fix round 1): a
   * `/documents` list item and its own `/documents/settings` sibling are
   * BOTH "active" (startsWith) while viewing Settings - resolving to
   * whichever came first in document order let the parent shadow the more
   * specific page, so both the crumb and the current-item highlight named
   * the wrong page. An exact match's path length equals the pathname's own
   * length, the ceiling any valid prefix can reach, so "prefer exact, else
   * longest prefix" collapses to a single length comparison.
   */
  const bestMatch = (
    items: MenuConfig,
  ): { item: MenuItem; breadcrumb: MenuItem[] } | undefined => {
    const matches = collectMatches(items);
    if (matches.length === 0) return undefined;
    return matches.reduce((best, candidate) =>
      (candidate.item.path?.length ?? 0) > (best.item.path?.length ?? 0)
        ? candidate
        : best,
    );
  };

  const getCurrentItem = (items: MenuConfig): MenuItem | undefined =>
    bestMatch(items)?.item;

  const getBreadcrumb = (items: MenuConfig): MenuItem[] =>
    bestMatch(items)?.breadcrumb ?? [];

  const getChildren = (items: MenuConfig, level: number): MenuConfig | null => {
    const hasActiveChildAtLevel = (items: MenuConfig): boolean => {
      for (const item of items) {
        if (
          (item.path &&
            (item.path === pathname ||
              (item.path !== '/' &&
                item.path !== '' &&
                pathname.startsWith(item.path)))) ||
          (item.children && hasActiveChildAtLevel(item.children))
        ) {
          return true;
        }
      }
      return false;
    };

    const findChildren = (
      items: MenuConfig,
      targetLevel: number,
      currentLevel: number = 0,
    ): MenuConfig | null => {
      for (const item of items) {
        if (item.children) {
          if (
            targetLevel === currentLevel &&
            hasActiveChildAtLevel(item.children)
          ) {
            return item.children;
          }
          const children = findChildren(
            item.children,
            targetLevel,
            currentLevel + 1,
          );
          if (children) {
            return children;
          }
        } else if (
          targetLevel === currentLevel &&
          item.path &&
          (item.path === pathname ||
            (item.path !== '/' &&
              item.path !== '' &&
              pathname.startsWith(item.path)))
        ) {
          return items;
        }
      }
      return null;
    };

    return findChildren(items, level);
  };

  return {
    isActive,
    hasActiveChild,
    isItemActive,
    getCurrentItem,
    getBreadcrumb,
    getChildren,
  };
};
