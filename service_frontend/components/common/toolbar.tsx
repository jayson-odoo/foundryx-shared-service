import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface ToolbarActionsProps {
  children?: ReactNode;
}

export interface ToolbarProps {
  children?: ReactNode;
}

export interface ToolbarTitleProps {
  children: ReactNode;
  className?: string;
}

export interface ToolbarHeadingProps {
  className?: string;
  children: ReactNode;
}

export const Toolbar = ({ children }: ToolbarProps) => {
  return (
    <div className="flex items-center justify-between grow gap-2.5 pb-5">
      {children}
    </div>
  );
};

export const ToolbarHeading = ({
  children,
  className,
}: ToolbarHeadingProps) => {
  return (
    <div className={cn('flex flex-col flex-wrap gap-px', className)}>
      {children}
    </div>
  );
};

export const ToolbarTitle = ({ className, children }: ToolbarTitleProps) => {
  // Heading level 2, not 1 (AC-DLA-27): `PageHeader` owns the one top-level
  // heading per page; this legacy toolbar title (unused today, kept for the
  // shared-component contract) must never compete with it.
  return (
    <h2 className={cn('font-semibold text-foreground text-lg', className)}>
      {children}
    </h2>
  );
};

export const ToolbarActions = ({ children }: ToolbarActionsProps) => {
  return (
    <div className="flex items-center flex-wrap gap-1.5 lg:gap-3.5">
      {children}
    </div>
  );
};
