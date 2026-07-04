/**
 * Mock permission catalog (Phase A). Mirrors what the backend `GET /permissions`
 * will return once per-module CSVs are synced into the `permissions` table. Note
 * the dynamic/custom actions — `orders.approve`, `reports.export` — proving the
 * catalog isn't locked to CRUD (plan 03 §2.1).
 */
import type { PermissionCatalog } from '@/types/permission';
import type { PermissionService } from './permission-service';
import { delay } from './mock-query';

const A = (key: string, action: string, actionLabel: string, description: string) => ({
  key,
  action,
  actionLabel,
  description,
});

const CRUD = (resource: string, noun: string) => [
  A(`${resource}.read`, 'read', 'Read', `View ${noun}`),
  A(`${resource}.create`, 'create', 'Create', `Create ${noun}`),
  A(`${resource}.update`, 'update', 'Update', `Edit ${noun}`),
  A(`${resource}.delete`, 'delete', 'Delete', `Delete ${noun}`),
];

export const MOCK_CATALOG: PermissionCatalog = [
  { module: 'Dashboard', resource: 'dashboard', resourceLabel: 'Dashboard', actions: [A('dashboard.read', 'read', 'Read', 'View dashboards')] },
  { module: 'User Management', resource: 'users', resourceLabel: 'Users', actions: CRUD('users', 'users') },
  { module: 'User Management', resource: 'roles', resourceLabel: 'Roles & Permissions', actions: CRUD('roles', 'roles') },
  { module: 'Events', resource: 'events', resourceLabel: 'Events', actions: CRUD('events', 'events') },
  {
    module: 'Orders & Delivery',
    resource: 'orders',
    resourceLabel: 'Orders & Delivery',
    actions: [...CRUD('orders', 'orders'), A('orders.approve', 'approve', 'Approve', 'Approve submitted orders')],
  },
  { module: 'Products', resource: 'products', resourceLabel: 'Products', actions: CRUD('products', 'products') },
  { module: 'Inventory', resource: 'inventory', resourceLabel: 'Inventory', actions: CRUD('inventory', 'inventory') },
  { module: 'Procurement', resource: 'procurement', resourceLabel: 'Procurement', actions: CRUD('procurement', 'procurement') },
  { module: 'Vendors', resource: 'vendors', resourceLabel: 'Vendors', actions: CRUD('vendors', 'vendors') },
  {
    module: 'Reports & Analytics',
    resource: 'reports',
    resourceLabel: 'Reports & Analytics',
    actions: [A('reports.read', 'read', 'Read', 'View reports'), A('reports.export', 'export', 'Export', 'Export reports')],
  },
  { module: 'Finance & Billing', resource: 'finance', resourceLabel: 'Finance & Billing', actions: CRUD('finance', 'finance') },
  {
    module: 'System Settings',
    resource: 'settings',
    resourceLabel: 'System Settings',
    actions: [A('settings.read', 'read', 'Read', 'View settings'), A('settings.update', 'update', 'Update', 'Change settings')],
  },
];

/** Every key in the catalog — used to seed the Admin role with full access. */
export const ALL_PERMISSION_KEYS: string[] = MOCK_CATALOG.flatMap((r) => r.actions.map((a) => a.key));

export const mockPermissionService: PermissionService = {
  async catalog() {
    return delay(MOCK_CATALOG, 200);
  },
};
