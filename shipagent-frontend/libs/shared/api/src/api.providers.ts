import { EnvironmentProviders } from '@angular/core';
import {
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  apiAuthInterceptor,
  apiErrorInterceptor,
} from './api.interceptors';

/** Provide ShipAgent's shared cookie authentication and API error mapping. */
export function provideShipAgentHttpClient(): EnvironmentProviders {
  return provideHttpClient(
    withInterceptors([apiAuthInterceptor, apiErrorInterceptor]),
  );
}
