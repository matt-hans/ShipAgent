/**
 * @shipagent/shared-api
 *
 * Angular HttpClient-based API service for ShipAgent.
 * Provides typed access to all backend endpoints and HTTP interceptors.
 * Consumed by all remotes and the shell app.
 */

export { ApiService } from './api.service';
export { API_BASE_URL } from './api-url.token';
export { apiErrorInterceptor, apiAuthInterceptor } from './api.interceptors';
export { provideShipAgentHttpClient } from './api.providers';
export { BrowserSessionState } from './browser-session.state';
export {
  ApiError,
  type ApiErrorBody,
  type PlatformActivationResponse,
} from './api.models';
