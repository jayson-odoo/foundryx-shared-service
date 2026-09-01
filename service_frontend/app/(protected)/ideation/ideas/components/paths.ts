/** Route helpers for the Ideas feature - single source of truth for its URLs. */

export const ideasListPath = '/ideation/ideas';
export const ideaNewPath = `${ideasListPath}/new`;
export const ideaFormPath = (id: string) => `${ideasListPath}/${id}`;

/** Form href, optionally in edit mode. */
export function ideaFormHref(id: string, opts?: { edit?: boolean }): string {
  return opts?.edit ? `${ideaFormPath(id)}?edit=1` : ideaFormPath(id);
}
