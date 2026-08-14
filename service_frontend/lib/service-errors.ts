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
