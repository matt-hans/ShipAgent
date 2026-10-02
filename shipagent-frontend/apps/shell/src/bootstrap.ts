/** Bootstrap Angular after any production Tauri same-origin handoff. */
import { signal } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';
import { API_BASE_URL } from '@shipagent/shared-api';
import { computeApiBaseUrl } from '@shipagent/shared-tauri';

async function bootstrap(): Promise<void> {
  const baseUrl = signal(computeApiBaseUrl());

  await bootstrapApplication(AppComponent, {
    ...appConfig,
    providers: [
      ...(appConfig.providers ?? []),
      { provide: API_BASE_URL, useValue: baseUrl },
    ],
  });
}

bootstrap().catch(console.error);
