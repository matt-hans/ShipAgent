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
import { BrowserSessionState } from './browser-session.state';

const BROWSER_SESSION_PATH = '/api/v1/auth/session';

function isBrowserSessionFlow(url: string): boolean {
  const path = url.split(/[?#]/, 1)[0].replace(/\/+$/, '');
  return path.endsWith(BROWSER_SESSION_PATH);
}

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
  const browserSession = inject(BrowserSessionState);

  return next(req).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse) {
        if (err.status === 401 && !isBrowserSessionFlow(req.url)) {
          browserSession.markExpired();
        }
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
 * Lets the browser attach same-origin HttpOnly session cookies, and enables
 * credentials for the Tauri sidecar URL. API keys are never sourced from
 * frontend configuration or persistent browser state.
 */
export const apiAuthInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  return next(req.clone({ withCredentials: true }));
};
