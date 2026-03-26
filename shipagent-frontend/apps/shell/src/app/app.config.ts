/**
 * Shell application configuration.
 *
 * Provides Zone.js change detection with event coalescing (recommended for
 * performance) and HttpClient with the error interceptor from shared-api.
 *
 * NOTE: Do NOT add provideExperimentalZonelessChangeDetection() — the shell
 * uses Zone.js by design (per research recommendation for stability).
 *
 * API_BASE_URL is injected at bootstrap time in bootstrap.ts after the Tauri
 * sidecar port has been resolved, so it is NOT provided here.
 */
import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { apiErrorInterceptor } from '@shipagent/shared-api';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideHttpClient(withInterceptors([apiErrorInterceptor])),
  ],
};
