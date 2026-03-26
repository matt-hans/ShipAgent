/**
 * Chat remote application configuration.
 *
 * Provides HttpClient (required for ApiService) and markdown support.
 * ngx-markdown's provideMarkdown() is also called at component level
 * in ChatContainerComponent for component-scoped configuration.
 */
import {
  ApplicationConfig,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { apiErrorInterceptor } from '@shipagent/shared-api';
import { provideMarkdown } from 'ngx-markdown';
import { appRoutes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(appRoutes),
    provideHttpClient(withInterceptors([apiErrorInterceptor])),
    provideMarkdown(),
  ],
};
