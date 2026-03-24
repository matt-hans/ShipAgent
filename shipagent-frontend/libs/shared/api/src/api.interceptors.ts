/**
 * HTTP interceptors for ShipAgent API communication.
 */

import {
  HttpInterceptorFn,
  HttpRequest,
  HttpHandlerFn,
  HttpErrorResponse,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ApiError, ApiErrorBody } from './api.models';

/**
 * apiErrorInterceptor
 *
 * Catches HTTP 4xx/5xx errors and maps them to typed ApiError instances.
 * Extracts the error body from the response and constructs a user-friendly message.
 */
export const apiErrorInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  return next(req).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse) {
        const body = err.error as ApiErrorBody | null;
        // Support both standard shape { message: "..." } and
        // nested connection shape { error: { message: "..." } }
        const nestedError = body as unknown as { error?: { message?: string } };
        const message =
          (typeof nestedError?.error?.message === 'string'
            ? nestedError.error.message
            : null) ||
          body?.message ||
          `HTTP ${err.status}: ${err.statusText}`;

        return throwError(() => new ApiError(err.status, body, message));
      }
      return throwError(() => err);
    }),
  );
};

/**
 * apiAuthInterceptor
 *
 * Adds the X-API-Key header when a key is configured.
 * Reads from the global SHIPAGENT_API_KEY environment injected at build time,
 * or falls back to a session-level key if available.
 *
 * No-op when no key is configured — allows anonymous access in dev mode.
 */
export const apiAuthInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  // Read API key from injected environment or skip.
  // The key is only needed when the backend is configured with SHIPAGENT_API_KEY.
  // The actual value is provided by the shell app via environment injection.
  try {
    const { SHIPAGENT_API_KEY } = inject(API_AUTH_KEY, { optional: true }) ?? {};
    if (SHIPAGENT_API_KEY) {
      const authReq = req.clone({
        setHeaders: { 'X-API-Key': SHIPAGENT_API_KEY },
      });
      return next(authReq);
    }
  } catch {
    // inject() called outside injection context — safe to ignore
  }
  return next(req);
};

import { InjectionToken } from '@angular/core';

/**
 * Optional injection token for the API auth key.
 * Provide this in the shell app when SHIPAGENT_API_KEY is configured.
 */
export const API_AUTH_KEY = new InjectionToken<{ SHIPAGENT_API_KEY?: string }>(
  'API_AUTH_KEY',
);
