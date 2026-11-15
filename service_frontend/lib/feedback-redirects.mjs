// Lane FEEDBACK-RENAME (owner ruling 15 Nov): every page URL that said
// idea / ideas / ideation moved to a feedback path. These PERMANENT redirects
// keep every link already sent (WhatsApp, email, bookmarks, the CRM iframe)
// working. Plain .mjs so next.config.mjs can import it at build time.
// Order matters: the specific rules run before the catch-all ones.

/** @type {{ source: string; destination: string; permanent: true }[]} */
export const FEEDBACK_REDIRECTS = [
  { source: '/ideation', destination: '/feedback', permanent: true },
  { source: '/ideation/ideas', destination: '/feedback', permanent: true },
  { source: '/ideation/ideas/:path*', destination: '/feedback/:path*', permanent: true },
  { source: '/ideation/:path*', destination: '/feedback/:path*', permanent: true },
  { source: '/embed/ideas/portal/feedback', destination: '/embed/feedback/portal/list', permanent: true },
  { source: '/embed/ideas', destination: '/embed/feedback', permanent: true },
  { source: '/embed/ideas/:path*', destination: '/embed/feedback/:path*', permanent: true },
  { source: '/public/ideas/:path*', destination: '/public/feedback/:path*', permanent: true },
  { source: '/portal/ideas/feedback', destination: '/portal/feedback/list', permanent: true },
  { source: '/portal/ideas', destination: '/portal/feedback', permanent: true },
  { source: '/portal/ideas/:path*', destination: '/portal/feedback/:path*', permanent: true },
];
