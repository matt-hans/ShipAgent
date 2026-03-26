/**
 * Shell bootstrap — resolves the Tauri sidecar port and provides API_BASE_URL
 * before bootstrapping the Angular application.
 *
 * In Tauri mode: invokes the sidecar, discovers the dynamic port, and provides
 * the full URL (http://127.0.0.1:{port}/api/v1).
 * In Vite dev mode: falls back to the relative proxy URL (/api/v1).
 */
import { signal } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';
import { API_BASE_URL } from '@shipagent/shared-api';
import { resolveSidecarPort } from '@shipagent/shared-tauri';

async function bootstrap(): Promise<void> {
  const port = await resolveSidecarPort();
  // In Tauri: use sidecar port. In dev: use localhost:8000 directly
  // (NF dev server doesn't support proxy passthrough).
  // In production: relative /api/v1 works since FastAPI serves the SPA.
  const devFallback = location.port === '4200' ? 'http://localhost:8000/api/v1' : '/api/v1';
  const baseUrl = signal(port ? `http://127.0.0.1:${port}/api/v1` : devFallback);

  await bootstrapApplication(AppComponent, {
    ...appConfig,
    providers: [
      ...(appConfig.providers ?? []),
      { provide: API_BASE_URL, useValue: baseUrl },
    ],
  });
}

bootstrap().catch(console.error);
