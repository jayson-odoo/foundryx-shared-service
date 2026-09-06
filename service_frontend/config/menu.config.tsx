import {
  Blocks,
  Building2,
  ClipboardList,
  Cog,
  FolderClosed,
  LayoutGrid,
  Lightbulb,
  MessageSquare,
  Video,
  Network,
  Package,
  Plug,
  RefreshCw,
  ShieldUser,
  Terminal,
  Users,
  Workflow,
} from 'lucide-react';
import { type MenuConfig } from './types';

export const MENU_SIDEBAR: MenuConfig = [
  // T7 fix round 1 - was a "Light Sidebar" / "Dark Sidebar" theme-demo
  // submenu (Metronic showcase leftovers, BL-SS-057); a single leaf to `/`
  // matches MENU_MEGA's "Home" entry (also a single leaf, no submenu).
  { title: 'Dashboards', icon: LayoutGrid, path: '/' },
  // Platform Console (plan 07) - operator-only: hidden unless the session user
  // is in the platform tenant AND can('tenants.read') (SidebarMenu filters).
  { heading: 'Platform', platformOnly: true },
  {
    title: 'Tenant Management',
    icon: Building2,
    platformOnly: true,
    children: [
      {
        title: 'Tenants',
        path: '/platform/tenants',
        permission: 'tenants.read',
      },
    ],
  },
  // Platform engines (sprint-2) - Status now; Workflow/Rule/Template later.
  // Menu rule: parents only group - every navigable path is a CHILD entry.
  {
    title: 'Platform Engines',
    icon: Network,
    platformOnly: true,
    children: [
      {
        title: 'Status Engine',
        path: '/platform/status-engine',
        permission: 'statuses.read',
      },
      // Rule engine observability (sprint-2/02 D12) - rules are edited where
      // they live; this list shows what exists + deep-links there.
      {
        title: 'Rules',
        path: '/platform/rules',
        permission: 'rules.read',
      },
    ],
  },
  { heading: 'Apps' },
  {
    title: 'App Store',
    icon: Blocks,
    children: [
      {
        title: 'App Store',
        path: '/app-store',
        permission: 'app_store.read',
      },
    ],
  },
  // Workflow engine (sprint-2/08) - tenant automation (trigger → action).
  {
    title: 'Workflows',
    icon: Workflow,
    termKey: 'workflow',
    children: [
      {
        title: 'All workflows',
        path: '/workflows',
        permission: 'workflows.read',
        termKey: 'workflow',
      },
    ],
  },
  // Form engine (sprint-3/01) - tenant-designed forms + submissions.
  {
    title: 'Forms',
    icon: ClipboardList,
    termKey: 'form',
    children: [
      {
        title: 'All forms',
        path: '/forms',
        permission: 'forms.read',
        termKey: 'form',
      },
    ],
  },
  // Import engine history (sprint-3/09, F8) - bulk-import jobs across entities.
  {
    title: 'Imports',
    icon: FolderClosed,
    path: '/imports',
    termKey: 'import',
  },
  // Centralized background jobs (sprint-4/10) - storage migration + future async
  // job types. Readable by any authed user (jobs are tenant-scoped server-side);
  // the migration controls are gated separately. Sidebar-only, mirroring Imports.
  {
    title: 'Jobs',
    icon: Cog,
    path: '/jobs',
  },
  // Developer Logs / Integration Activity console (sprint-4/12) - inbound API /
  // embed / outbound / webhook activity for troubleshooting. Gated
  // integration_logs.read (filterMenu prunes it when absent).
  {
    title: 'Developers',
    icon: Terminal,
    children: [
      {
        title: 'Logs',
        path: '/developers/logs',
        permission: 'integration_logs.read',
      },
      {
        title: 'Log settings',
        path: '/developers/logs/settings',
        permission: 'integration_logs.manage',
      },
    ],
  },
  // Document management / the Drive (sprint-3/04) - files, folders, sharing.
  {
    title: 'Documents',
    icon: FolderClosed,
    termKey: 'document',
    children: [
      {
        title: 'All documents',
        path: '/documents',
        permission: 'documents.read',
        termKey: 'document',
      },
      {
        title: 'Shared links',
        path: '/documents/shares',
        permission: 'documents.share',
      },
      {
        title: 'Document types',
        path: '/documents/types',
        permission: 'documents.configure',
      },
      {
        title: 'Settings',
        path: '/documents/settings',
        permission: 'documents.configure',
      },
    ],
  },
  // Tenant-scoped settings (renamed from "Workspace Settings" in sprint-2/06
  // D9 - "workspace" collided with omnichannel's messaging workspaces, and
  // "tenant" is platform vocabulary that shouldn't leak into white-label UI).
  // Pages gate themselves by permission (per-permission menu pruning = BL-014).
  {
    title: 'Settings',
    icon: Plug,
    children: [
      // General workspace settings (sprint-4/08) - tenant default currency, etc.
      {
        title: 'General',
        path: '/settings/general',
        permission: 'settings.read',
      },
      {
        title: 'Integrations',
        path: '/settings/integrations',
        permission: 'integrations.read',
        termKey: 'connection',
      },
      // Per-tenant entity relabeling (sprint-3/08, F10). Read-for-all,
      // edit gated terminology.manage.
      {
        title: 'Terminology',
        path: '/settings/terminology',
        permission: 'terminology.manage',
      },
      // Document numbering engine (sprint-4/07, Cluster F) - per-tenant prefixes /
      // formats / reset cadence / next values. Gated numbering.manage.
      {
        title: 'Numbering',
        path: '/settings/numbering',
        permission: 'numbering.manage',
      },
      // Tenant surface of the status engine (sprint-2/01) - fork-on-edit.
      {
        title: 'Statuses',
        path: '/settings/statuses',
        permission: 'statuses.read',
      },
      // Tenant surface of the rule engine (sprint-2/02) - read-only registry.
      {
        title: 'Rules',
        path: '/settings/rules',
        permission: 'rules.read',
      },
      // Tenant white-label branding (sprint-2/03) - gated by branding.read.
      {
        title: 'Branding',
        path: '/settings/branding',
        permission: 'branding.read',
      },
      // Template engine (sprint-2/07) - email templates + outbox surfacing.
      {
        title: 'Templates',
        path: '/settings/templates',
        permission: 'templates.read',
        termKey: 'template',
      },
      {
        title: 'Email log',
        path: '/settings/email-log',
        permission: 'emails.read',
      },
      // Workflow engine tenant settings (plan sprint-2/10) - run retention.
      {
        title: 'Workflows',
        path: '/settings/workflows',
        permission: 'workflows.manage',
      },
      // Import engine tenant settings (plan sprint-3/09 D11) - per-tenant caps.
      {
        title: 'Import settings',
        path: '/settings/imports',
        permission: 'imports.read_all',
      },
      // Core AI subsystem (Phase B-i slice 1). Agents + skills share
      // `ai_agents.read`; traces carry their OWN key so raw prompts/completions
      // can be granted separately (AC-BI-14). LLM connections live under
      // Integrations - they ride `integrations.read/manage`, no new permission.
      {
        title: 'AI agents',
        path: '/settings/ai/agents',
        permission: 'ai_agents.read',
      },
      {
        title: 'AI skills',
        path: '/settings/ai/skills',
        permission: 'ai_agents.read',
      },
      {
        title: 'AI traces',
        path: '/settings/ai/traces',
        permission: 'ai_traces.read',
      },
    ],
  },
  {
    title: 'User Management',
    icon: ShieldUser,
    children: [
      {
        title: 'Users',
        path: '/user-management/users',
        permission: 'users.read',
      },
      {
        title: 'Roles',
        path: '/user-management/roles',
        permission: 'roles.read',
      },
      // Permissions/Account/Logs/Settings entries removed in sprint-2/06 -
      // Metronic demo residue, the routes never existed (404 on click).
    ],
  },
  // Products catalog (CORE master-data). Top-level, not under Ideation - the
  // Product is a core system entity Ideation extends, not an Ideation artifact.
  {
    title: 'Products',
    icon: Package,
    path: '/products',
    permission: 'products.read',
  },
  // Ideation module (plan: documentation/plans/ideation/, Phase A). Ungated for
  // the Phase-1 prototype; TODO(Phase 2): add `module: 'ideation'` + per-child
  // `permission` once the ideation App-Store module + permissions are seeded.
  {
    title: 'Ideation',
    icon: Lightbulb,
    children: [
      { title: 'Ideas', path: '/ideation/ideas' },
      {
        title: 'Business requirements',
        path: '/ideation/business-requirements',
        permission: 'ideation.business_requirements.read',
      },
      { title: 'Triage board', path: '/ideation/board' },
      {
        title: 'Embed connections',
        path: '/ideation/embed-connections',
        permission: 'ideation.triage.manage',
      },
    ],
  },
  // Module menu block - visible only while the module is ACTIVE for the
  // tenant (plan 08 §8, lands BL-014 for module items).
  {
    title: 'Omnichannel',
    icon: MessageSquare,
    module: 'omnichannel',
    children: [
      {
        title: 'Inbox',
        path: '/omnichannel/inbox',
        permission: 'conversations.read',
      },
      {
        title: 'Channels',
        path: '/omnichannel/settings/channels',
        permission: 'channels.read',
      },
      {
        title: 'Workspaces',
        path: '/omnichannel/settings/workspaces',
        permission: 'workspaces.read',
      },
      {
        title: 'Media limits',
        path: '/omnichannel/settings/media',
        permission: 'channels.manage',
      },
      {
        title: 'Quick replies',
        path: '/omnichannel/settings/quick-replies',
        permission: 'workspaces.manage',
      },
      {
        title: 'Embed access',
        path: '/omnichannel/settings/embed',
        permission: 'workspaces.manage',
      },
    ],
  },
  // Meetings (sprint-5 S0) - module menu block, visible only while the
  // `meetings` module is ACTIVE for the tenant AND the user holds the key its
  // page gates on (filterMenu prunes at every level). No clickable parent.
  {
    title: 'Meetings',
    icon: Video,
    module: 'meetings',
    children: [
      {
        title: 'My meetings',
        path: '/meetings/my-meetings',
        permission: 'meetings.view',
      },
      {
        title: 'Settings',
        path: '/settings/meetings',
        permission: 'meetings.settings.manage',
      },
    ],
  },
  // AutoCount ESB (sprint-4/13) - module menu block, visible only while the
  // `autocount` module is ACTIVE for the tenant AND the user holds the key its
  // page gates on (filterMenu prunes at every level).
  {
    title: 'AutoCount',
    icon: RefreshCw,
    module: 'autocount',
    children: [
      {
        title: 'Companies',
        path: '/autocount/companies',
        permission: 'autocount.companies.read',
      },
      {
        title: 'Review',
        path: '/autocount/review',
        permission: 'autocount.sync.read',
      },
    ],
  },
];

export const MENU_MEGA: MenuConfig = [
  { title: 'Home', path: '/' },
  {
    title: 'Apps',
    children: [
      {
        title: 'User Management',
        children: [
          {
            children: [
              {
                title: 'Users',
                path: '/user-management/users',
                permission: 'users.read',
              },
              {
                title: 'Roles',
                path: '/user-management/roles',
                permission: 'roles.read',
              },
            ],
          },
        ],
      },
      {
        title: 'Developers',
        children: [
          {
            children: [
              {
                title: 'Logs',
                path: '/developers/logs',
                permission: 'integration_logs.read',
              },
              {
                title: 'Log settings',
                path: '/developers/logs/settings',
                permission: 'integration_logs.manage',
              },
            ],
          },
        ],
      },
      // Meetings (sprint-5 S0) - the DESKTOP mega menu copy. Same module +
      // permission tags, so `filterMenu` prunes it identically in all three.
      {
        title: 'Meetings',
        module: 'meetings',
        children: [
          {
            children: [
              {
                title: 'My meetings',
                path: '/meetings/my-meetings',
                permission: 'meetings.view',
              },
              {
                title: 'Settings',
                path: '/settings/meetings',
                permission: 'meetings.settings.manage',
              },
            ],
          },
        ],
      },
      // AutoCount ESB (sprint-4/13) - the DESKTOP mega menu. demo1 renders
      // MENU_SIDEBAR, MENU_MEGA and MENU_MEGA_MOBILE, so an entry present in
      // the mobile mega but absent here is visible on a phone and missing on a
      // desktop. Same module + permission tags, so `filterMenu` prunes it
      // identically in all three copies.
      {
        title: 'AutoCount',
        module: 'autocount',
        children: [
          {
            children: [
              {
                title: 'Companies',
                path: '/autocount/companies',
                permission: 'autocount.companies.read',
              },
              {
                title: 'Review',
                path: '/autocount/review',
                permission: 'autocount.sync.read',
              },
            ],
          },
        ],
      },
    ],
  },
];

export const MENU_MEGA_MOBILE: MenuConfig = [
  { title: 'Home', path: '/' },
  {
    title: 'User Management',
    icon: Users,
    children: [
      {
        title: 'Users',
        path: '/user-management/users',
        permission: 'users.read',
      },
      {
        title: 'Roles',
        path: '/user-management/roles',
        permission: 'roles.read',
      },
    ],
  },
  {
    title: 'Developers',
    icon: Terminal,
    children: [
      {
        title: 'Logs',
        path: '/developers/logs',
        permission: 'integration_logs.read',
      },
      {
        title: 'Log settings',
        path: '/developers/logs/settings',
        permission: 'integration_logs.manage',
      },
    ],
  },
  // Meetings (sprint-5 S0) - third menu copy; same module + permission tags so
  // the mobile mega menu prunes identically.
  {
    title: 'Meetings',
    icon: Video,
    module: 'meetings',
    children: [
      {
        title: 'My meetings',
        path: '/meetings/my-meetings',
        permission: 'meetings.view',
      },
      {
        title: 'Settings',
        path: '/settings/meetings',
        permission: 'meetings.settings.manage',
      },
    ],
  },
  // AutoCount ESB (sprint-4/13) - third menu copy; same module + permission
  // tags so the mobile mega menu prunes identically.
  {
    title: 'AutoCount',
    icon: RefreshCw,
    module: 'autocount',
    children: [
      {
        title: 'Companies',
        path: '/autocount/companies',
        permission: 'autocount.companies.read',
      },
      {
        title: 'Review',
        path: '/autocount/review',
        permission: 'autocount.sync.read',
      },
    ],
  },
];
