import { PageSkeleton } from '@/components/platform/skeletons/page-skeleton';

// Neutral fallback for every segment that has no more specific loading.tsx
// of its own (a non-list/non-record page - settings/general, branding,
// omnichannel/inbox, forms/[id]/fill, imports, jobs/[id], documents,
// platform/rules, ...). Fix round 1 item 1: this used to render
// ListPageSkeleton, which drew a grid + pagination strip that never matched
// what the page actually became. ListPageSkeleton/RecordPageSkeleton stay
// strictly scoped to their own qualifying segments' loading.tsx files.
export default function Loading() {
  return <PageSkeleton />;
}
