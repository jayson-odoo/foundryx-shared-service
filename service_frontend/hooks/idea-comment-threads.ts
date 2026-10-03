import type { IdeaComment, IdeaCommentThread } from '@/types/ideation';

/**
 * Group the flat, oldest-first comment list into threads (plan 19, AC-19-22):
 * each top-level comment with its replies (one level, order preserved). A reply
 * whose parent is not in the list becomes its own thread rather than vanishing.
 */
export function groupCommentThreads(
  comments: IdeaComment[],
): IdeaCommentThread[] {
  const known = new Set(comments.map((c) => c.id));
  const threads = new Map<string, IdeaCommentThread>();
  for (const c of comments) {
    if (c.parentId === null || !known.has(c.parentId))
      threads.set(c.id, { root: c, replies: [] });
  }
  for (const c of comments) {
    if (c.parentId !== null && known.has(c.parentId))
      threads.get(c.parentId)?.replies.push(c);
  }
  return Array.from(threads.values());
}

/** Live comments shown (a deleted placeholder is not counted). */
export function countLiveComments(comments: IdeaComment[]): number {
  return comments.filter((c) => !c.isDeleted).length;
}
