'use client';

/**
 * `<FxOff>`: everything inside behaves as if the Foundryx UIUX switch were
 * off, whatever this browser chose (`useFx()` returns false under it). Mounted
 * by `app/embed/layout.tsx`, because pages embedded in a host app keep the
 * host's look. On mount it also clears the switch's `<html>` attributes, for
 * the rare same-origin embed whose browser has the switch on; the cookie is
 * left alone. Renders no DOM of its own.
 */
import { createContext, useEffect, type ReactNode } from 'react';

export const FxOffContext = createContext(false);

const FX_HTML_ATTRS = [
  'data-fx',
  'data-fx-pal',
  'data-fx-dpal',
  'data-fx-font',
];

export function FxOff({ children }: { children: ReactNode }) {
  useEffect(() => {
    const html = document.documentElement;
    for (const name of FX_HTML_ATTRS) html.removeAttribute(name);
    html.style.removeProperty('--fx-scale');
  }, []);
  return <FxOffContext.Provider value={true}>{children}</FxOffContext.Provider>;
}
