/**
 * HTTP interceptors for ShipAgent API communication.
 */

import {
  HttpInterceptorFn,
  HttpRequest,
  HttpHandlerFn,
  HttpErrorResponse,
} from '@angular/common/http';
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
