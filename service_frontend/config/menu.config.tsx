import {
  AlertCircle,
  Bell,
  Blocks,
  Building2,
  Captions,
  CheckCircle,
  ClipboardList,
  Coffee,
  Cog,
  Euro,
  Eye,
  FileQuestion,
  FolderClosed,
  HelpCircle,
  Key,
  LayoutGrid,
  LifeBuoy,
  Lightbulb,
  MessageSquare,
  Network,
  Package,
  Plug,
  RefreshCw,
  Settings,
  Share2,
  Shield,
  ShieldUser,
  ShoppingCart,
  Star,
  Terminal,
  UserCheck,
  UserCircle,
  Users,
  Workflow,
} from 'lucide-react';
import { type MenuConfig } from './types';

export const MENU_SIDEBAR: MenuConfig = [
  {
    title: 'Dashboards',
    icon: LayoutGrid,
    children: [
      { title: 'Light Sidebar', path: '/' },
      { title: 'Dark Sidebar', path: '/dark-sidebar' },
    ],
  },
  { heading: 'User' },
  {
    title: 'My Account',
    icon: Settings,
    children: [
      {
        title: 'Account',
        children: [
          { title: 'Get Started', path: '/account/home/get-started' },
          { title: 'User Profile', path: '/account/home/user-profile' },
          { title: 'Company Profile', path: '/account/home/company-profile' },
          {
            title: 'Settings - With Sidebar',
            path: '/account/home/settings-sidebar',
          },
          {
            title: 'Settings - Enterprise',
            path: '/account/home/settings-enterprise',
          },
          { title: 'Settings - Plain', path: '/account/home/settings-plain' },
          { title: 'Settings - Modal', path: '/account/home/settings-modal' },
        ],
      },
      {
        title: 'Billing',
        children: [
          { title: 'Billing - Basic', path: '/account/billing/basic' },
          {
            title: 'Billing - Enterprise',
            path: '/account/billing/enterprise',
          },
          { title: 'Plans', path: '/account/billing/plans' },
          { title: 'Billing History', path: '/account/billing/history' },
        ],
      },
      {
        title: 'Security',
        children: [
          { title: 'Get Started', path: '/account/security/get-started' },
          { title: 'Security Overview', path: '/account/security/overview' },
          {
            title: 'Allowed IP Addresses',
            path: '/account/security/allowed-ip-addresses',
          },
          {
            title: 'Privacy Settings',
            path: '/account/security/privacy-settings',
          },
          {
            title: 'Device Management',
            path: '/account/security/device-management',
          },
          {
            title: 'Backup & Recovery',
            path: '/account/security/backup-and-recovery',
          },
          {
            title: 'Current Sessions',
            path: '/account/security/current-sessions',
          },
          { title: 'Security Log', path: '/account/security/security-log' },
        ],
      },
      {
        title: 'Members & Roles',
        children: [
          { title: 'Teams Starter', path: '/account/members/team-starter' },
          { title: 'Teams', path: '/account/members/teams' },
          { title: 'Team Info', path: '/account/members/team-info' },
          {
            title: 'Members Starter',
            path: '/account/members/members-starter',
          },
          { title: 'Team Members', path: '/account/members/team-members' },
          { title: 'Import Members', path: '/account/members/import-members' },
          { title: 'Roles', path: '/account/members/roles' },
          {
            title: 'Permissions - Toggler',
            path: '/account/members/permissions-toggle',
          },
          {
            title: 'Permissions - Check',
            path: '/account/members/permissions-check',
          },
        ],
      },
      { title: 'Integrations', path: '/account/integrations' },
      { title: 'Notifications', path: '/account/notifications' },
      { title: 'API Keys', path: '/account/api-keys' },
      {
        title: 'More',
        collapse: true,
        collapseTitle: 'Show less',
        expandTitle: 'Show 3 more',
        children: [
          { title: 'Appearance', path: '/account/appearance' },
          { title: 'Invite a Friend', path: '/account/invite-a-friend' },
          { title: 'Activity', path: '/account/activity' },
        ],
      },
    ],
  },
  {
    title: 'Authentication',
    icon: Shield,
    children: [
      {
        title: 'Sign In',
        path: '/signin',
      },
      {
        title: 'Check Email',
        path: '/signup',
      },
      {
        title: 'Reset Password',
        path: '/reset-password',
      },
      {
        title: '2FA',
        path: '/2fa',
      },
      { title: 'Welcome Message', path: '/auth/welcome-message' },
      { title: 'Account Deactivated', path: '/auth/account-deactivated' },
      { title: 'Error 404', path: '/error/404' },
      { title: 'Error 500', path: '/error/500' },
    ],
  },
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

export const MENU_SIDEBAR_CUSTOM: MenuConfig = [
  {
    title: 'Store - Client',
    icon: Users,
    children: [
      { title: 'Home', path: '/store-client/home' },
      {
        title: 'Search Results',
        children: [
          {
            title: 'Search Results - Grid',
            path: '/store-client/search-results-grid',
          },
          {
            title: 'Search Results - List',
            path: '/store-client/search-results-list',
          },
        ],
      },
      {
        title: 'Overlays',
        children: [
          { title: 'Product Details', path: '/store-client/product-details' },
          { title: 'Wishlist', path: '/store-client/wishlist' },
        ],
      },
      {
        title: 'Checkout',
        children: [
          {
            title: 'Order Summary',
            path: '/store-client/checkout/order-summary',
          },
          {
            title: 'Shipping Info',
            path: '/store-client/checkout/shipping-info',
          },
          {
            title: 'Payment Method',
            path: '/store-client/checkout/payment-method',
          },
          {
            title: 'Order Placed',
            path: '/store-client/checkout/order-placed',
          },
        ],
      },
      { title: 'My Orders', path: '/store-client/my-orders' },
      { title: 'Order Receipt', path: '/store-client/order-receipt' },
    ],
  },
];

export const MENU_SIDEBAR_COMPACT: MenuConfig = [
  {
    title: 'Dashboards',
    icon: LayoutGrid,
    path: '/',
  },
  {
    title: 'Public Profile',
    icon: UserCircle,
    children: [
      {
        title: 'Profiles',
        children: [
          { title: 'Default', path: '/public-profile/profiles/default' },
          { title: 'Creator', path: '/public-profile/profiles/creator' },
          { title: 'Company', path: '/public-profile/profiles/company' },
          { title: 'NFT', path: '/public-profile/profiles/nft' },
          { title: 'Blogger', path: '/public-profile/profiles/blogger' },
          { title: 'CRM', path: '/public-profile/profiles/crm' },
          {
            title: 'More',
            collapse: true,
            collapseTitle: 'Show less',
            expandTitle: 'Show 4 more',
            children: [
              { title: 'Gamer', path: '/public-profile/profiles/gamer' },
              { title: 'Feeds', path: '/public-profile/profiles/feeds' },
              { title: 'Plain', path: '/public-profile/profiles/plain' },
              { title: 'Modal', path: '/public-profile/profiles/modal' },
            ],
          },
        ],
      },
      {
        title: 'Projects',
        children: [
          { title: '3 Columns', path: '/public-profile/projects/3-columns' },
          { title: '2 Columns', path: '/public-profile/projects/2-columns' },
        ],
      },
      { title: 'Works', path: '/public-profile/works' },
      { title: 'Teams', path: '/public-profile/teams' },
      { title: 'Network', path: '/public-profile/network' },
      { title: 'Activity', path: '/public-profile/activity' },
      {
        title: 'More',
        collapse: true,
        collapseTitle: 'Show less',
        expandTitle: 'Show 3 more',
        children: [
          { title: 'Campaigns - Card', path: '/public-profile/campaigns/card' },
          { title: 'Campaigns - List', path: '/public-profile/campaigns/list' },
          { title: 'Empty', path: '/public-profile/empty' },
        ],
      },
    ],
  },
  {
    title: 'My Account',
    icon: Settings,
    children: [
      {
        title: 'Account',
        children: [
          { title: 'Get Started', path: '/account/home/get-started' },
          { title: 'User Profile', path: '/account/home/user-profile' },
          { title: 'Company Profile', path: '/account/home/company-profile' },
          {
            title: 'Settings - With Sidebar',
            path: '/account/home/settings-sidebar',
          },
          {
            title: 'Settings - Enterprise',
            path: '/account/home/settings-enterprise',
          },
          { title: 'Settings - Plain', path: '/account/home/settings-plain' },
          { title: 'Settings - Modal', path: '/account/home/settings-modal' },
        ],
      },
      {
        title: 'Billing',
        children: [
          { title: 'Billing - Basic', path: '/account/billing/basic' },
          {
            title: 'Billing - Enterprise',
            path: '/account/billing/enterprise',
          },
          { title: 'Plans', path: '/account/billing/plans' },
          { title: 'Billing History', path: '/account/billing/history' },
        ],
      },
      {
        title: 'Security',
        children: [
          { title: 'Get Started', path: '/account/security/get-started' },
          { title: 'Security Overview', path: '/account/security/overview' },
          {
            title: 'Allowed IP Addresses',
            path: '/account/security/allowed-ip-addresses',
          },
          {
            title: 'Privacy Settings',
            path: '/account/security/privacy-settings',
          },
          {
            title: 'Device Management',
            path: '/account/security/device-management',
          },
          {
            title: 'Backup & Recovery',
            path: '/account/security/backup-and-recovery',
          },
          {
            title: 'Current Sessions',
            path: '/account/security/current-sessions',
          },
          { title: 'Security Log', path: '/account/security/security-log' },
        ],
      },
      {
        title: 'Members & Roles',
        children: [
          { title: 'Teams Starter', path: '/account/members/team-starter' },
          { title: 'Teams', path: '/account/members/teams' },
          { title: 'Team Info', path: '/account/members/team-info' },
          {
            title: 'Members Starter',
            path: '/account/members/members-starter',
          },
          { title: 'Team Members', path: '/account/members/team-members' },
          { title: 'Import Members', path: '/account/members/import-members' },
          { title: 'Roles', path: '/account/members/roles' },
          {
            title: 'Permissions - Toggler',
            path: '/account/members/permissions-toggle',
          },
          {
            title: 'Permissions - Check',
            path: '/account/members/permissions-check',
          },
        ],
      },
      { title: 'Integrations', path: '/account/integrations' },
      { title: 'Notifications', path: '/account/notifications' },
      { title: 'API Keys', path: '/account/api-keys' },
      {
        title: 'More',
        collapse: true,
        collapseTitle: 'Show less',
        expandTitle: 'Show 3 more',
        children: [
          { title: 'Appearance', path: '/account/appearance' },
          { title: 'Invite a Friend', path: '/account/invite-a-friend' },
          { title: 'Activity', path: '/account/activity' },
        ],
      },
    ],
  },
  {
    title: 'Network',
    icon: Users,
    children: [
      { title: 'Get Started', path: '/network/get-started' },
      {
        title: 'User Cards',
        children: [
          { title: 'Mini Cards', path: '/network/user-cards/mini-cards' },
          { title: 'Team Crew', path: '/network/user-cards/team-crew' },
          { title: 'Author', path: '/network/user-cards/author' },
          { title: 'NFT', path: '/network/user-cards/nft' },
          { title: 'Social', path: '/network/user-cards/social' },
        ],
      },
      {
        title: 'User Table',
        children: [
          { title: 'Team Crew', path: '/network/user-table/team-crew' },
          { title: 'App Roster', path: '/network/user-table/app-roster' },
          {
            title: 'Market Authors',
            path: '/network/user-table/market-authors',
          },
          { title: 'SaaS Users', path: '/network/user-table/saas-users' },
          { title: 'Store Clients', path: '/network/user-table/store-clients' },
          { title: 'Visitors', path: '/network/user-table/visitors' },
        ],
      },
      { title: 'Cooperations', path: '/network/cooperations', disabled: true },
      { title: 'Leads', path: '/network/leads', disabled: true },
      { title: 'Donators', path: '/network/donators', disabled: true },
    ],
  },
  {
    title: 'Store - Client',
    icon: ShoppingCart,
    children: [
      { title: 'Home', path: '/store-client/home' },
      {
        title: 'Search Results - Grid',
        path: '/store-client/search-results-grid',
      },
      {
        title: 'Search Results - List',
        path: '/store-client/search-results-list',
      },
      { title: 'Product Details', path: '/store-client/product-details' },
      { title: 'Wishlist', path: '/store-client/wishlist' },
      {
        title: 'Checkout',
        children: [
          {
            title: 'Order Summary',
            path: '/store-client/checkout/order-summary',
          },
          {
            title: 'Shipping Info',
            path: '/store-client/checkout/shipping-info',
          },
          {
            title: 'Payment Method',
            path: '/store-client/checkout/payment-method',
          },
          {
            title: 'Order Placed',
            path: '/store-client/checkout/order-placed',
          },
        ],
      },
      { title: 'My Orders', path: '/store-client/my-orders' },
      { title: 'Order Receipt', path: '/store-client/order-receipt' },
    ],
  },
  {
    title: 'User Management',
    icon: ShieldUser,
    children: [
      {
        title: 'Users',
        path: '/user-management/users',
      },
      {
        title: 'Roles',
        path: '/user-management/roles',
      },
      // Permissions/Account/Logs/Settings entries removed in sprint-2/06 -
      // Metronic demo residue, the routes never existed (404 on click).
    ],
  },
  // Products catalog (CORE master-data) - top-level, not under Ideation.
  {
    title: 'Products',
    icon: Package,
    path: '/products',
    permission: 'products.read',
  },
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
    ],
  },
  {
    title: 'Omnichannel',
    icon: MessageSquare,
    children: [
      {
        title: 'Inbox',
        path: '/omnichannel/inbox',
      },
      {
        title: 'Channels',
        path: '/omnichannel/settings/channels',
      },
      {
        title: 'Workspaces',
        path: '/omnichannel/settings/workspaces',
      },
      {
        title: 'Media limits',
        path: '/omnichannel/settings/media',
      },
      {
        title: 'Quick replies',
        path: '/omnichannel/settings/quick-replies',
      },
      {
        title: 'Embed access',
        path: '/omnichannel/settings/embed',
      },
    ],
  },
  // AutoCount ESB (sprint-4/13) - tagged so the mega menu prunes it exactly
  // like the sidebar (the mega menus are SEPARATE copies; an untagged entry
  // here would leak a gated path).
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
  {
    title: 'Authentication',
    icon: Shield,
    children: [
      {
        title: 'Sign In',
        path: '/signin',
      },
      {
        title: 'Check Email',
        path: '/signup',
      },
      {
        title: 'Reset Password',
        path: '/reset-password',
      },
      {
        title: '2FA',
        path: '/2fa',
      },
      { title: 'Welcome Message', path: '/auth/welcome-message' },
      { title: 'Account Deactivated', path: '/auth/account-deactivated' },
      { title: 'Error 404', path: '/error/404' },
      { title: 'Error 500', path: '/error/500' },
    ],
  },
];

export const MENU_MEGA: MenuConfig = [
  { title: 'Home', path: '/' },
  {
    title: 'My Account',
    children: [
      {
        title: 'General Pages',
        children: [
          { title: 'Integrations', icon: Plug, path: '/account/integrations' },
          {
            title: 'Notifications',
            icon: Bell,
            path: '/account/notifications',
          },
          { title: 'API Keys', icon: Key, path: '/account/api-keys' },
          { title: 'Appearance', icon: Eye, path: '/account/appearance' },
          {
            title: 'Invite a Friend',
            icon: UserCheck,
            path: '/account/invite-a-friend',
          },
          { title: 'Activity', icon: LifeBuoy, path: '/account/activity' },
          { title: 'Brand', icon: CheckCircle, disabled: true },
          { title: 'Get Paid', icon: Euro, disabled: true },
        ],
      },
      {
        title: 'Other pages',
        children: [
          {
            title: 'Account Home',
            children: [
              { title: 'Get Started', path: '/account/home/get-started' },
              { title: 'User Profile', path: '/account/home/user-profile' },
              {
                title: 'Company Profile',
                path: '/account/home/company-profile',
              },
              { title: 'With Sidebar', path: '/account/home/settings-sidebar' },
              {
                title: 'Enterprise',
                path: '/account/home/settings-enterprise',
              },
              { title: 'Plain', path: '/account/home/settings-plain' },
              { title: 'Modal', path: '/account/home/settings-modal' },
            ],
          },
          {
            title: 'Security',
            children: [
              { title: 'Get Started', path: '/account/security/get-started' },
              {
                title: 'Security Overview',
                path: '/account/security/overview',
              },
              {
                title: 'IP Addresses',
                path: '/account/security/allowed-ip-addresses',
              },
              {
                title: 'Privacy Settings',
                path: '/account/security/privacy-settings',
              },
              {
                title: 'Device Management',
                path: '/account/security/device-management',
              },
              {
                title: 'Backup & Recovery',
                path: '/account/security/backup-and-recovery',
              },
              {
                title: 'Current Sessions',
                path: '/account/security/current-sessions',
              },
              { title: 'Security Log', path: '/account/security/security-log' },
            ],
          },
        ],
      },
    ],
  },
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
    title: 'My Account',
    children: [
      {
        title: 'General Pages',
        children: [
          { title: 'Integrations', icon: Plug, path: '/account/integrations' },
          {
            title: 'Notifications',
            icon: Bell,
            path: '/account/notifications',
          },
          { title: 'API Keys', icon: Key, path: '/account/api-keys' },
          { title: 'Appearance', icon: Eye, path: '/account/appearance' },
          {
            title: 'Invite a Friend',
            icon: UserCheck,
            path: '/account/invite-a-friend',
          },
          { title: 'Activity', icon: LifeBuoy, path: '/account/activity' },
          { title: 'Brand', icon: CheckCircle, disabled: true },
          { title: 'Get Paid', icon: Euro, disabled: true },
        ],
      },
      {
        title: 'Other pages',
        children: [
          {
            title: 'Account Home',
            children: [
              { title: 'Get Started', path: '/account/home/get-started' },
              { title: 'User Profile', path: '/account/home/user-profile' },
              {
                title: 'Company Profile',
                path: '/account/home/company-profile',
              },
              { title: 'With Sidebar', path: '/account/home/settings-sidebar' },
              {
                title: 'Enterprise',
                path: '/account/home/settings-enterprise',
              },
              { title: 'Plain', path: '/account/home/settings-plain' },
              { title: 'Modal', path: '/account/home/settings-modal' },
            ],
          },
          {
            title: 'Security',
            children: [
              { title: 'Get Started', path: '/account/security/get-started' },
              {
                title: 'Security Overview',
                path: '/account/security/overview',
              },
              {
                title: 'IP Addresses',
                path: '/account/security/allowed-ip-addresses',
              },
              {
                title: 'Privacy Settings',
                path: '/account/security/privacy-settings',
              },
              {
                title: 'Device Management',
                path: '/account/security/device-management',
              },
              {
                title: 'Backup & Recovery',
                path: '/account/security/backup-and-recovery',
              },
              {
                title: 'Current Sessions',
                path: '/account/security/current-sessions',
              },
              { title: 'Security Log', path: '/account/security/security-log' },
            ],
          },
        ],
      },
    ],
  },
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

export const MENU_HELP: MenuConfig = [
  {
    title: 'Getting Started',
    icon: Coffee,
    path: 'https://keenthemes.com/metronic/tailwind/docs/getting-started/installation',
  },
  {
    title: 'Support Forum',
    icon: AlertCircle,
    children: [
      {
        title: 'All Questions',
        icon: FileQuestion,
        path: 'https://devs.keenthemes.com',
      },
      {
        title: 'Popular Questions',
        icon: Star,
        path: 'https://devs.keenthemes.com/popular',
      },
      {
        title: 'Ask Question',
        icon: HelpCircle,
        path: 'https://devs.keenthemes.com/question/create',
      },
    ],
  },
  {
    title: 'Licenses & FAQ',
    icon: Captions,
    path: 'https://keenthemes.com/metronic/tailwind/docs/getting-started/license',
  },
  {
    title: 'Documentation',
    icon: FileQuestion,
    path: 'https://keenthemes.com/metronic/tailwind/docs',
  },
  { separator: true },
  { title: 'Contact Us', icon: Share2, path: 'https://keenthemes.com/contact' },
];

export const MENU_ROOT: MenuConfig = [
  {
    title: 'Public Profile',
    icon: UserCircle,
    rootPath: '/public-profile/',
    path: '/public-profile/profiles/default',
    childrenIndex: 2,
  },
  {
    title: 'Account',
    icon: Settings,
    rootPath: '/account/',
    path: '/',
    childrenIndex: 3,
  },
  {
    title: 'Network',
    icon: Users,
    rootPath: '/network/',
    path: '/network/get-started',
    childrenIndex: 4,
  },
  {
    title: 'Authentication',
    icon: Shield,
    rootPath: '/authentication/',
    path: '/authentication/get-started',
    childrenIndex: 5,
  },
  {
    title: 'Store - Client',
    icon: ShoppingCart,
    rootPath: '/store-client/',
    path: '/store-client/home',
    childrenIndex: 6,
  },
  {
    title: 'User Management',
    icon: ShieldUser,
    rootPath: '/user-management/',
    path: '/user-management/users',
    childrenIndex: 7,
  },
];
