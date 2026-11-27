import type { FieldHint } from '@/types/integration';

/** Mirrors the backend range (`http_source/gentle.py`). */
export const PAGE_PAUSE_MAX_SECONDS = 90;

/**
 * SS-STOCK-PAGE-PAUSE-CONFIG - "About N pages per run → about X min per run"
 * for the pause field, recomputed live from the value being typed: the last
 * run's time with its own pauses swapped for the typed pause. It says so when
 * that passes the time a run may take, or when concurrent pages switch the
 * pause off. `null` while the typed value is not a valid pause (the save
 * shows the error) or no run is known yet.
 */
export function fieldHintText(
  hint: FieldHint | undefined,
  value: string | undefined,
  config: Record<string, string> = {},
): string | null {
  if (!hint || hint.kind !== 'pageRun' || hint.pages < 1) return null;
  const raw = (value ?? '').trim();
  const pause = raw === '' ? 0 : Number(raw);
  if (!Number.isFinite(pause) || pause < 0 || pause > PAGE_PAUSE_MAX_SECONDS) return null;
  const concurrent = Number((config.maxConcurrentPages ?? '').trim() || '1');
  if (pause > 0 && Number.isFinite(concurrent) && concurrent > 1) {
    return 'Not used while Max concurrent pages is above 1.';
  }
  const gaps = Math.max(hint.pages - 1, 0);
  const requestSeconds = Math.max(hint.lastRunSeconds - gaps * hint.lastPauseSeconds, 0);
  const totalSeconds = requestSeconds + gaps * pause;
  const pages = `About ${hint.pages} ${hint.pages === 1 ? 'page' : 'pages'} per run`;
  const minutes = Math.round(totalSeconds / 60);
  const time = minutes < 1 ? 'under 1 min per run' : `about ${minutes} min per run`;
  if (hint.maxRunSeconds > 0 && totalSeconds > hint.maxRunSeconds) {
    return `${pages} → ${time}, longer than the ${Math.round(hint.maxRunSeconds / 60)} min a run may take.`;
  }
  return `${pages} → ${time}`;
}
