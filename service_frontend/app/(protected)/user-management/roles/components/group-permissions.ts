import type { PermissionResource } from '@/types/permission';

export interface PermissionGroup {
  module: string;
  /** The section header a user reads (e.g. "Feedback"), never the raw key. */
  label: string;
  resources: PermissionResource[];
}

const readable = (module: string): string => {
  const words = module.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** Groups the permission catalog by owning module, in catalog order. */
export function groupPermissionsByModule(catalog: PermissionResource[]): PermissionGroup[] {
  const byModule = new Map<string, PermissionGroup>();
  for (const res of catalog) {
    const group = byModule.get(res.module) ?? {
      module: res.module,
      label: res.moduleLabel || readable(res.module),
      resources: [],
    };
    group.resources.push(res);
    byModule.set(res.module, group);
  }
  return Array.from(byModule.values());
}
