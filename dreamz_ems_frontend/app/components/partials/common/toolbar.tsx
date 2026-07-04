'use client';

import { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { MENU_SIDEBAR } from '@/config/menu.config';
import { useMenu } from '@/hooks/use-menu';
import { useTerminology } from '@/hooks/use-terminology';

const Toolbar = ({ children }: { children: ReactNode }) => {
  return (
    <div className="flex flex-wrap items-center lg:items-end justify-between gap-5 pb-7.5">
      {children}
    </div>
  );
};

const ToolbarActions = ({ children }: { children: ReactNode }) => {
  return <div className="flex items-center gap-2.5">{children}</div>;
};

const ToolbarPageTitle = ({ text }: { text?: string }) => {
  const pathname = usePathname();
  const { getCurrentItem } = useMenu(pathname);
  const { labelPlural } = useTerminology();
  const item = getCurrentItem(MENU_SIDEBAR);
  // Relabelable entries resolve their plural via terminology (F10); the static
  // title is the fallback (never blank).
  const resolved = item?.termKey ? labelPlural(item.termKey) : item?.title;

  return (
    <h1 className="text-xl font-medium leading-none text-mono">
      {text ?? resolved}
    </h1>
  );
};

const ToolbarDescription = ({ children }: { children: ReactNode }) => {
  return (
    <div className="flex items-center gap-2 text-sm font-normal text-secondary-foreground">
      {children}
    </div>
  );
};

const ToolbarHeading = ({ children }: { children: ReactNode }) => {
  return <div className="flex flex-col justify-center gap-2">{children}</div>;
};

export {
  Toolbar,
  ToolbarActions,
  ToolbarPageTitle,
  ToolbarHeading,
  ToolbarDescription,
};
