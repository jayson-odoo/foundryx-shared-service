'use client';

import * as React from 'react';
import { ThemeProvider as NextThemesProvider } from 'next-themes';

// The tooltip provider lives ONLY in `providers/tooltips-provider.tsx`
// (AC-DLA-16) - this file wrapping its own would be a second provider racing
// the app-wide 700ms delay.
export function ThemeProvider({
  children,
}: React.ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      storageKey="nextjs-theme"
      enableSystem
      disableTransitionOnChange
      enableColorScheme
    >
      {children}
    </NextThemesProvider>
  );
}
