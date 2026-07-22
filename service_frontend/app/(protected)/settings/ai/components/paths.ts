export const AI_AGENTS_PATH = '/settings/ai/agents';
export const AI_SKILLS_PATH = '/settings/ai/skills';
export const AI_TRACES_PATH = '/settings/ai/traces';

export function agentPath(id: string): string {
  return `${AI_AGENTS_PATH}/${id}`;
}

export function skillPath(id: string): string {
  return `${AI_SKILLS_PATH}/${id}`;
}

export function tracePath(id: string): string {
  return `${AI_TRACES_PATH}/${id}`;
}

/** Form href preserving record-nav context (ctx + index), optionally edit mode. */
function formHref(base: string, opts?: { ctx?: string; index?: number; edit?: boolean }): string {
  const params = new URLSearchParams();
  if (opts?.edit) params.set('edit', '1');
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export function agentFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  return formHref(agentPath(id), opts);
}

export function skillFormHref(
  id: string,
  opts?: { ctx?: string; index?: number; edit?: boolean },
): string {
  return formHref(skillPath(id), opts);
}
