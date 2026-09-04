'use client';

import { ReactNode, useEffect } from 'react';
import { useIsMobile } from '@/hooks/use-mobile';
import { useSettings } from '@/providers/settings-provider';
import { Footer } from './components/footer';
import { Header } from './components/header';
import { Sidebar } from './components/sidebar';

export function Demo1Layout({ children }: { children: ReactNode }) {
  const isMobile = useIsMobile();
  const { settings, setOption } = useSettings();

  useEffect(() => {
    const bodyClass = document.body.classList;

    if (settings.layouts.demo1.sidebarCollapse) {
      bodyClass.add('sidebar-collapse');
    } else {
      bodyClass.remove('sidebar-collapse');
    }

    // T3 fix round 1 finding 9: `layout-initialized` (the class that turns
    // the sidebar width transition ON) is scheduled from THIS effect now,
    // one frame after `sidebar-collapse` is applied right above - not from
    // the mount effect below. `SettingsProvider` hydrates
    // `sidebarCollapse` from localStorage in an effect of ITS OWN that
    // fires AFTER this component's mount effect has already run (a second
    // render, once localStorage is read) - so a returning collapsed-sidebar
    // user previously got `layout-initialized` (enabling the transition)
    // BEFORE the hydrated `sidebar-collapse` class ever landed, then
    // watched the wrapper visibly slide into the collapsed width once it
    // did. Tying the class to THIS effect means it always trails the
    // specific settings-driven class change it exists to guard, on every
    // settings update, not just the first one.
    const raf = requestAnimationFrame(() => {
      bodyClass.add('layout-initialized');
    });
    return () => cancelAnimationFrame(raf);
  }, [settings]); // Runs only on settings update

  useEffect(() => {
    // Set current layout
    setOption('layout', 'demo1');
  }, [setOption]);

  useEffect(() => {
    const bodyClass = document.body.classList;

    // Add a class to the body element
    bodyClass.add('demo1');
    bodyClass.add('sidebar-fixed');
    bodyClass.add('header-fixed');

    // `layout-initialized` itself is scheduled from the `[settings]` effect
    // above (T3 fix round 1 finding 9) - this effect only owns mount/unmount
    // of the shell's structural classes now.
    return () => {
      bodyClass.remove('demo1');
      bodyClass.remove('sidebar-fixed');
      bodyClass.remove('sidebar-collapse');
      bodyClass.remove('header-fixed');
      bodyClass.remove('layout-initialized');
    };
  }, []); // Runs only once on mount

  return (
    <>
      {!isMobile && <Sidebar />}

      {/* min-w-0: the wrapper is a flex item of the horizontal body flex -
          without it, any page content with a wide min-content (tab strips,
          toolbars) blows the whole layout past the viewport on mobile
          instead of shrinking/scrolling within its own box (sprint-3/01
          responsive sweep). */}
      <div className="wrapper flex min-w-0 grow flex-col">
        <Header />

        <main className="grow pt-5" role="content">
          {children}
        </main>

        <Footer />
      </div>
    </>
  );
}
