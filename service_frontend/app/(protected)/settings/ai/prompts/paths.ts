export const AI_PROMPTS_PATH = '/settings/ai/prompts';

export function promptPath(name: string): string {
  return `${AI_PROMPTS_PATH}/${encodeURIComponent(name)}`;
}
