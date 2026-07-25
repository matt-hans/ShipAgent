import { Injectable, inject } from '@angular/core';
import { firstValueFrom, fromEvent, takeUntil } from 'rxjs';
import { ApiService } from './api.service';
import { API_BASE_URL } from './api-url.token';
import { BrowserSessionState } from './browser-session.state';
import {
  BROWSER_CSRF_HEADER,
  isBrowserSessionFlow,
  isShipAgentApiFlow,
  isUnsafeHttpMethod,
} from './browser-session-request';

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

@Injectable({ providedIn: 'root' })
export class BrowserSessionTransportService {
  private readonly apiService = inject(ApiService);
  private readonly apiBaseUrl = inject(API_BASE_URL);
  private readonly browserSession = inject(BrowserSessionState);

  async fetch(
    input: RequestInfo | URL,
    init: RequestInit = {}
  ): Promise<Response> {
    const inputRequest =
      typeof Request !== 'undefined' && input instanceof Request ? input : null;
    const method = (init.method ?? inputRequest?.method ?? 'GET').toUpperCase();
    const csrfToken = this.browserSession.csrfToken();
    const requestInit: RequestInit = {
      ...init,
      credentials: 'include',
    };

    if (
      isUnsafeHttpMethod(method) &&
      isShipAgentApiFlow(requestUrl(input), this.apiBaseUrl()) &&
      !isBrowserSessionFlow(requestUrl(input)) &&
      csrfToken
    ) {
      const headers = new Headers(init.headers ?? inputRequest?.headers);
      headers.set(BROWSER_CSRF_HEADER, csrfToken);
      requestInit.headers = headers;
    }

    const response = await globalThis.fetch(input, requestInit);
    if (response.status === 401) {
      this.browserSession.markExpired();
    }
    return response;
  }

  async confirmSessionAfterEventSourceError(
    abortSignal?: AbortSignal
  ): Promise<boolean> {
    if (abortSignal?.aborted) return false;
    try {
      const statusRequest = this.apiService.getBrowserSessionStatus();
      const status = await firstValueFrom(
        abortSignal
          ? statusRequest.pipe(takeUntil(fromEvent(abortSignal, 'abort')))
          : statusRequest
      );
      if (abortSignal?.aborted) return false;
      this.browserSession.applySessionStatus(status);
      if (status.required && !status.authenticated) {
        this.browserSession.markExpired();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }
}
