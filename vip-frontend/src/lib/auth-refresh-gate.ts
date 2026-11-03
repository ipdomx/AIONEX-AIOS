/**
 * Single-flight, session-aware guard around `POST /auth/refresh`.
 *
 * Production nginx rate-limits `/auth/refresh` per IP. A client that refreshes
 * for anonymous visitors, on every polling 401, or again after a refresh has
 * already failed turns into a retry loop. This gate guarantees that:
 *
 * - no refresh is attempted without a local session hint (anonymous visitors);
 * - concurrent callers share one in-flight refresh promise;
 * - a failed refresh is never retried immediately: a terminal failure
 *   (400/401/403/429) clears the local session once, and every failure starts
 *   an exponential backoff with jitter (honouring `Retry-After`);
 * - the returned promise never rejects, so network/CORS failures cannot become
 *   unhandled promise rejections.
 *
 * The module is dependency free so it can be unit tested with `node --test`.
 */

export class RefreshFailure extends Error {
  readonly status: number | null;
  readonly retryAfterMs: number | null;

  constructor(status: number | null, retryAfterMs: number | null = null) {
    super(
      status === null
        ? "Session refresh failed (network)"
        : `Session refresh failed with status ${status}`,
    );
    this.name = "RefreshFailure";
    this.status = status;
    this.retryAfterMs = retryAfterMs;
  }
}

export interface RefreshGateOptions {
  hasSessionHint: () => boolean;
  clearSession: () => void;
  now?: () => number;
  random?: () => number;
  baseBackoffMs?: number;
  maxBackoffMs?: number;
}

export interface RefreshGate<T> {
  /** Resolves with the refreshed value, or `null` when no refresh happened or it failed. */
  run(perform: () => Promise<T>): Promise<T | null>;
  /** Forget failures, e.g. after an explicit successful login. */
  reset(): void;
  /** Epoch milliseconds before which no refresh will be attempted. */
  blockedUntil(): number;
}

const TERMINAL_STATUSES = new Set([400, 401, 403, 429]);

export function isTerminalRefreshStatus(status: number | null): boolean {
  return status !== null && TERMINAL_STATUSES.has(status);
}

export function parseRetryAfterMs(
  value: string | null | undefined,
  now: number = Date.now(),
): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed) * 1000;
  const date = Date.parse(trimmed);
  if (Number.isNaN(date)) return null;
  return Math.max(0, date - now);
}

export function refreshBackoffMs(
  failures: number,
  random: number,
  baseMs: number,
  maxMs: number,
  retryAfterMs: number | null = null,
): number {
  const exponent = Math.max(0, Math.min(failures - 1, 16));
  const ceiling = Math.min(maxMs, baseMs * 2 ** exponent);
  const jitter = Math.min(1, Math.max(0, random));
  const delay = Math.round(ceiling / 2 + (ceiling / 2) * jitter);
  return Math.max(delay, retryAfterMs ?? 0);
}

export function createRefreshGate<T>(
  options: RefreshGateOptions,
): RefreshGate<T> {
  const now = options.now ?? (() => Date.now());
  const random = options.random ?? (() => Math.random());
  const baseMs = options.baseBackoffMs ?? 30_000;
  const maxMs = options.maxBackoffMs ?? 15 * 60_000;
  let inFlight: Promise<T | null> | null = null;
  let failures = 0;
  let blockedUntil = 0;

  function safeHint(): boolean {
    try {
      return options.hasSessionHint();
    } catch {
      return false;
    }
  }

  function onFailure(error: unknown): null {
    const status = error instanceof RefreshFailure ? error.status : null;
    const retryAfterMs =
      error instanceof RefreshFailure ? error.retryAfterMs : null;
    failures += 1;
    blockedUntil =
      now() + refreshBackoffMs(failures, random(), baseMs, maxMs, retryAfterMs);
    if (isTerminalRefreshStatus(status)) {
      try {
        options.clearSession();
      } catch {
        // Clearing local storage must never turn into an unhandled rejection.
      }
    }
    return null;
  }

  return {
    run(perform) {
      if (inFlight) return inFlight;
      if (!safeHint()) return Promise.resolve(null);
      if (now() < blockedUntil) return Promise.resolve(null);
      let attempt: Promise<T>;
      try {
        attempt = perform();
      } catch (error) {
        return Promise.resolve(onFailure(error));
      }
      const current = attempt
        .then(
          (value) => {
            failures = 0;
            blockedUntil = 0;
            return value;
          },
          (error: unknown) => onFailure(error),
        )
        .finally(() => {
          if (inFlight === current) inFlight = null;
        });
      inFlight = current;
      return current;
    },
    reset() {
      failures = 0;
      blockedUntil = 0;
    },
    blockedUntil() {
      return blockedUntil;
    },
  };
}
