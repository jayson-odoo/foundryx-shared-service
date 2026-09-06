'use client';

import { Demo1LightSidebarPage } from './components/demo1';

// AC-DLA-60 - demo2-10 dashboard content pages are deleted (D8, D15); demo1
// is the only mounted layout, so this route no longer branches on
// `settings.layout`.
export default function Page() {
  return <Demo1LightSidebarPage />;
}
