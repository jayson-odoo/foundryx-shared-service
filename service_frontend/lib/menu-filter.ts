import { MenuConfig, MenuItem } from '@/config/types';

/**
 * Menu visibility pruning (BL-014, plan sprint-2/05) — ONE recursive pass over
 * a MenuConfig applying every visibility gate at every level:
 *
 * - `platformOnly`  → platform-tenant members holding tenants.read (plan 07 §5)
 * - `module`        → entry visible only while the module is ACTIVE (plan 08 §8)
 * - `permission`    → entry visible only while the session holds the key
 * - parents (items whose `children` filter to zero) disappear — parents are
 *   non-clickable grouping per the shell rules, so an empty one is dead weight.
 *
 * Pure function (UX gate only — require_permission / require_module on the
 * backend stay the real boundary); the sidebar calls it once per render.
 */
export interface MenuVisibilityContext {
  /** session permission check — `useCan().can` */
  can: (permission: string) => boolean;
  /** App-Store module ACTIVE check — `useInstalledModules().isActive` */
  isModuleActive: (module: string) => boolean;
  /** installed-modules fetch settled — module-tagged items stay hidden until ready */
  modulesReady: boolean;
  /** platform-tenant member with tenants.read */
  showPlatform: boolean;
}

function itemVisible(item: MenuItem, ctx: MenuVisibilityContext): boolean {
  if (item.platformOnly && !ctx.showPlatform) return false;
  if (item.module && !(ctx.modulesReady && ctx.isModuleActive(item.module)))
    return false;
  if (item.permission && !ctx.can(item.permission)) return false;
  return true;
}

export function filterMenu(
  items: MenuConfig,
  ctx: MenuVisibilityContext,
): MenuConfig {
  return pruneOrphanHeadings(filterItems(items, ctx));
}

function filterItems(items: MenuConfig, ctx: MenuVisibilityContext): MenuConfig {
  const result: MenuConfig = [];
  for (const item of items) {
    if (!itemVisible(item, ctx)) continue;
    if (item.children) {
      const children = filterItems(item.children, ctx);
      // Parent with zero visible children disappears (shell rule: parents
      // only group — nothing left to navigate to).
      if (children.length === 0) continue;
      result.push({ ...item, children });
    } else {
      result.push(item);
    }
  }
  return result;
}

/** A heading whose entire section was pruned (no items before the next
 * heading) is dead weight too — drop it. */
function pruneOrphanHeadings(items: MenuConfig): MenuConfig {
  return items.filter((item, i) => {
    if (!item.heading) return true;
    const next = items[i + 1];
    return next !== undefined && !next.heading;
  });
}

