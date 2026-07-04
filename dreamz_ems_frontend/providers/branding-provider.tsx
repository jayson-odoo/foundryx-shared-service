'use client';

import { ReactNode, useEffect } from 'react';
import { useTheme } from 'next-themes';
import type { PublicBranding } from '@/types/branding';
import { overrideVars, TOKEN_DEFS } from '@/lib/branding-tokens';
import { useTenantBranding } from '@/hooks/use-branding';

function applyFavicon(branding: PublicBranding): void {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  link.href = branding.faviconUrl ?? branding.logoUrl ?? '';
}

/**
 * Applies the current host's tenant branding globally (sprint-2/03):
 *  - theme-token overrides as inline CSS custom properties on <html>
 *    (inline style beats both the `:root` and `.dark` stylesheet blocks, and
 *    is NOT an injected <style> tag — governance-clean);
 *  - browser-tab title (tenant name) + favicon when branded.
 *
 * Phase A applies client-side off the mock service. Phase B adds the real
 * first-paint path (backend theme.css <link> + generateMetadata by host);
 * this provider stays for instant in-session updates after edits.
 */
export function BrandingProvider({ children }: { children: ReactNode }) {
  const { branding, isResolved } = useTenantBranding();
  const { resolvedTheme } = useTheme();

  // Theme variables — re-applied whenever branding or light/dark flips.
  useEffect(() => {
    if (!isResolved) return;
    const root = document.documentElement;
    const theme = resolvedTheme === 'dark' ? 'dark' : 'light';
    const vars = overrideVars(branding.tokens, theme);
    for (const d of TOKEN_DEFS) {
      const transparent = `${d.cssVar}-transparent`;
      if (vars[d.cssVar]) root.style.setProperty(d.cssVar, vars[d.cssVar]);
      else root.style.removeProperty(d.cssVar);
      if (vars[transparent])
        root.style.setProperty(transparent, vars[transparent]);
      else root.style.removeProperty(transparent);
    }
  }, [branding, isResolved, resolvedTheme]);

  // Tab title + favicon. generateMetadata handles first paint, but its value
  // can be STALE (the SSR branding fetch is revalidate-cached) and Next 15
  // STREAMS metadata — the <title> may land AFTER this effect ran and clobber
  // it. The observer re-asserts the fresh client-resolved name whenever the
  // head rewrites the title (found via the branding E2E).
  useEffect(() => {
    if (!isResolved || !branding.isBranded) return;
    if (branding.tenantName) {
      const name = branding.tenantName;
      const apply = () => {
        if (document.title !== name) document.title = name;
      };
      apply();
      const observer = new MutationObserver(apply);
      observer.observe(document.head, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      if (branding.faviconUrl || branding.logoUrl) applyFavicon(branding);
      return () => observer.disconnect();
    }
    if (branding.faviconUrl || branding.logoUrl) applyFavicon(branding);
  }, [branding, isResolved]);

  return <>{children}</>;
}
