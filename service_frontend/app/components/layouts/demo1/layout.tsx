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

    // AC-DLA-24: the class only needs to land AFTER the browser has painted
    // the shell's initial (un-transitioned) layout at least once, so the
    // very first paint never carries a `transition` that would animate FROM
    // nothing. A 1000ms `setTimeout` guessed at that; a double
    // `requestAnimationFrame` (first frame commits the initial paint,
    // second frame runs after the browser has had a chance to render it)
    // is the actual signal and lands within two frames instead of a full
    // second.
    let raf1 = 0;
    let raf2 = 0;
    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        bodyClass.add('layout-initialized');
      });
    });

    // Remove the class when the component is unmounted
    return () => {
      bodyClass.remove('demo1');
      bodyClass.remove('sidebar-fixed');
      bodyClass.remove('sidebar-collapse');
      bodyClass.remove('header-fixed');
      bodyClass.remove('layout-initialized');
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
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
