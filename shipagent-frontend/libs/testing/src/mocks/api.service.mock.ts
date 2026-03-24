/**
 * ApiService mock for unit tests.
 *
 * Provides a spy object with all ApiService methods stubbed.
 * By default, each method returns an EMPTY Observable (completes without emitting).
 * Override specific methods with jasmine.spy.and.returnValue() in your test.
 */

import { of } from 'rxjs';

/** Names of all Observable-returning methods on ApiService. */
const API_SERVICE_METHODS = [
  // Conversations
  'createConversation',
  'sendMessage',
  'getConversations',
  'getConversationMessages',
  'deleteConversation',
  'deleteAllConversations',
  'renameConversation',
  'exportConversation',
  'saveArtifact',
  'uploadDocument',
  // Jobs
  'getJobs',
  'getJob',
  'getJobRows',
  'confirmJob',
  'cancelJob',
  'deleteJob',
  'skipFailedRows',
  'getJobProgress',
  // Data Sources
  'importDataSource',
  'uploadDataSource',
  'disconnectDataSource',
  'getDataSourceStatus',
  // Saved Sources
  'getSavedSources',
  'reconnectSavedSource',
  'deleteSavedSource',
  'bulkDeleteSavedSources',
  // Platforms
  'connectPlatform',
  'disconnectPlatform',
  'getPlatformEnvStatus',
  'getPlatformOrders',
  'getPlatformConnections',
  'activateShopify',
  'activateAmazon',
  'testPlatformConnection',
  // Connections (provider)
  'listProviderConnections',
  'getProviderConnection',
  'saveProviderCredentials',
  'deleteProviderConnection',
  'validateProviderConnection',
  'disconnectProvider',
  // Settings
  'getSettings',
  'patchSettings',
  'putCredential',
  'getCredentialStatus',
  'completeOnboarding',
  // Contacts
  'getContacts',
  'getContactByHandle',
  'createContact',
  'updateContact',
  'deleteContact',
  'searchContacts',
  // Commands
  'getCommands',
  'createCommand',
  'updateCommand',
  'deleteCommand',
] as const;

/** URL-returning methods (synchronous string returns). */
const URL_METHODS = [
  'getStreamUrl',
  'getJobProgressUrl',
  'getMergedLabelsUrl',
  'getZipLabelsUrl',
] as const;

/** Type representing all method names. */
type ApiServiceMethodName = (typeof API_SERVICE_METHODS)[number];
type ApiServiceUrlMethodName = (typeof URL_METHODS)[number];

/** Spy type for Observable methods. */
type ObservableSpy = jasmine.Spy<() => ReturnType<typeof of>>;

/** Spy type for URL methods. */
type UrlSpy = jasmine.Spy<() => string>;

/** Full mock type with all spied methods. */
export type MockApiService = {
  [K in ApiServiceMethodName]: ObservableSpy;
} & {
  [K in ApiServiceUrlMethodName]: UrlSpy;
};

/**
 * Create a mock ApiService with all methods stubbed.
 *
 * Observable methods return `of(undefined)` by default.
 * URL methods return an empty string by default.
 *
 * @example
 * ```typescript
 * const mockApi = createMockApiService();
 * mockApi.getSettings.and.returnValue(of(settingsFixture));
 *
 * TestBed.configureTestingModule({
 *   providers: [{ provide: ApiService, useValue: mockApi }]
 * });
 * ```
 */
export function createMockApiService(): MockApiService {
  const mock: Record<string, jasmine.Spy> = {};

  for (const method of API_SERVICE_METHODS) {
    mock[method] = jasmine.createSpy(method).and.returnValue(of(undefined));
  }

  for (const method of URL_METHODS) {
    mock[method] = jasmine.createSpy(method).and.returnValue('');
  }

  return mock as MockApiService;
}
