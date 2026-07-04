import { ReactNode, Suspense } from 'react';
import { Metadata } from 'next';
import { Inter, Poppins } from 'next/font/google';
import { getRequestBranding, themeCssHref } from '@/lib/branding-ssr';
import { cn } from '@/lib/utils';
import { AuthProvider } from '@/providers/auth-provider';
import { BrandingProvider } from '@/providers/branding-provider';
import { I18nProvider } from '@/providers/i18n-provider';
import { ModulesProvider } from '@/providers/modules-provider';
import { QueryProvider } from '@/providers/query-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { ThemeProvider } from '@/providers/theme-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { Toaster } from '@/components/ui/sonner';
import '@/css/styles.css';
import '@/components/keenicons/assets/styles.css';

// Inter = body/UI font; Poppins = FoundryX display font (headings, brand). Both exposed as CSS vars.
const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });
const poppins = Poppins({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-poppins',
});

/**
 * Tab title + favicon by request host (sprint-2/03 Phase B). Branded tenant =
 * its name + icon; everything else = FoundryX defaults. BrandingProvider keeps
 * these fresh client-side after in-session edits.
 */
export async function generateMetadata(): Promise<Metadata> {
  const { branding } = await getRequestBranding();
  if (branding?.isBranded && branding.tenantName) {
    const icon = branding.faviconUrl ?? branding.logoUrl;
    return {
      title: {
        template: `%s | ${branding.tenantName}`,
        default: branding.tenantName,
      },
      ...(icon ? { icons: { icon } } : {}),
    };
  }
  return {
    title: {
      template: '%s | FoundryX EMS',
      default: 'FoundryX EMS', // a default is required when creating a template
    },
  };
}

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  // First-paint theming (plan 03): the backend-generated override stylesheet
  // loads before any content renders — no flash of FoundryX orange on branded
  // tenants. First in <body>: a body stylesheet blocks rendering of the
  // content AFTER it and cascades after the bundled foundryx-tokens.css, so
  // tenant values win ties. Unbranded/unreachable = harmless empty CSS.
  const { slug, branding } = await getRequestBranding();

  return (
    <html className="h-full" suppressHydrationWarning>
      <body
        className={cn(
          'antialiased flex h-full text-base text-foreground bg-background',
          inter.variable,
          poppins.variable,
          inter.className,
        )}
      >
        {branding?.isBranded && (
          <link rel="stylesheet" href={themeCssHref(slug, branding.version)} />
        )}
        <QueryProvider>
          <AuthProvider>
            <SettingsProvider>
              <ThemeProvider>
                <BrandingProvider>
                  <I18nProvider>
                    <TooltipsProvider>
                      <ModulesProvider>
                        <Suspense>{children}</Suspense>
                        <Toaster />
                      </ModulesProvider>
                    </TooltipsProvider>
                  </I18nProvider>
                </BrandingProvider>
              </ThemeProvider>
            </SettingsProvider>
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
