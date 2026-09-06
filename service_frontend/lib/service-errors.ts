/**
 * Shared service-layer error classes (review extraction, plan sprint-2/04) -
 * one class identity across services so `instanceof` checks in hooks never
 * miss because two services declared their own copies.
 */

/** Single-use token rejected (invalid, expired, or already used). */
export class InvalidTokenError extends Error {}

/** Throttled (HTTP 429). `retryAfterSeconds` mirrors the Retry-After header. */
export class RateLimitError extends Error {
  retryAfterSeconds: number | null;
  constructor(message: string, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = 'RateLimitError';
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/**
 * A `background_jobs`-backed export (plan 26 D-A2-6a) hasn't finished inside
 * the caller's short wait window. The job keeps running - `jobId` lets the
 * caller point the user at the Jobs surface instead of a bare failure
 * ("never a silent failure"). Any future export/async-download flow should
 * reuse this identity rather than declare its own.
 */
export class ExportPendingError extends Error {
  jobId: string;
  constructor(message: string, jobId: string) {
    super(message);
    this.name = 'ExportPendingError';
    this.jobId = jobId;
  }
}
