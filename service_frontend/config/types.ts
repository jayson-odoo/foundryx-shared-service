import { type LucideIcon } from 'lucide-react';

export interface MenuItem {
  title?: string;
  icon?: LucideIcon;
  path?: string;
  rootPath?: string;
  childrenIndex?: number;
  heading?: string;
  children?: MenuConfig;
  disabled?: boolean;
  collapse?: boolean;
  collapseTitle?: string;
  expandTitle?: string;
  badge?: string;
  separator?: boolean;
  /** Visible only to platform-tenant users holding tenants.read (plan 07 §5). */
  platformOnly?: boolean;
  /** Visible only while this App-Store module is ACTIVE for the tenant (plan 08 §8). */
  module?: string;
  /** Visible only while the session holds this permission key (BL-014, plan sprint-2/05). */
  permission?: string;
  /**
   * Terminology key (plan sprint-3/08, F10). When set, the rendered label =
   * `labelPlural(termKey)` resolved via `useTerminology` (falls back to the
   * static `title`). Tag the matching entry in EVERY menu array.
   */
  termKey?: string;
}

export type MenuConfig = MenuItem[];

export interface Settings {
  container: 'fixed' | 'fluid';
  layout: string;
  layouts: {
    demo1: {
      sidebarCollapse: boolean;
      sidebarTheme: 'light' | 'dark';
    };
    demo2: {
      headerSticky: boolean;
      headerStickyOffset: number;
    };
    demo5: {
      headerSticky: boolean;
      headerStickyOffset: number;
    };
    demo7: {
      headerSticky: boolean;
      headerStickyOffset: number;
    };
    demo9: {
      headerSticky: boolean;
      headerStickyOffset: number;
    };
  };
}
