'use client';

import { ReactNode } from 'react';

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

// The old toolbar page-title component is retired for
// `components/platform/page-header` (AC-DLA-27, plan 23 D6) - the one
// page-title header, terminology-aware, with the sidebar-derived breadcrumb
// trail. `Toolbar`/`ToolbarActions`/`ToolbarHeading`/`ToolbarDescription` stay
// for non-resource pages that still want a plain toolbar row without a title.
export { Toolbar, ToolbarActions, ToolbarHeading, ToolbarDescription };
