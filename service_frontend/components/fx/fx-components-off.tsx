'use client';

/**
 * `<FxComponentsOff>`: components inside render their legacy look whatever
 * this browser chose (`useFx()` and `useFxSetting()` return off under it),
 * while the global look (font, size, scrollbars on `<html>`) is left exactly
 * as the switch set it. Mounted by the sign-in group, the public portal group
 * and the WhatsApp callback, which only get the global look
 * (playbook-uiux.md). Unlike `<FxOff>` it never touches `<html>`. Renders no
 * DOM of its own.
 */
import { createContext, type ReactNode } from 'react';

export const FxComponentsOffContext = createContext(false);

export function FxComponentsOff({ children }: { children: ReactNode }) {
  return (
    <FxComponentsOffContext.Provider value={true}>
      {children}
    </FxComponentsOffContext.Provider>
  );
}
