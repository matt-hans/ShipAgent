/**
 * @shipagent/testing
 *
 * Shared test infrastructure: mocks, fixtures, and utilities.
 * Import in test files only — never in production code.
 *
 * Usage: import { conversationFixtures, createMockApiService } from '@shipagent/testing';
 */

// Mocks
export { createMockApiService } from './mocks/api.service.mock';
export type { MockApiService } from './mocks/api.service.mock';
export { createMockSseService } from './mocks/sse.service.mock';
export type { MockSseService, RawSseEvent } from './mocks/sse.service.mock';
export {
  createMockConversationState,
  createMockJobState,
  createMockDataSourceState,
  createMockSettingsState,
  createMockContactsState,
  createMockCommandsState,
  createMockPlatformsState,
  createMockAppState,
} from './mocks/store.mocks';
export type {
  MockConversationStoreState,
  MockJobStoreState,
  MockDataSourceStoreState,
  MockSettingsStoreState,
  MockContactsStoreState,
  MockCommandsStoreState,
  MockPlatformsStoreState,
  MockAppStoreState,
} from './mocks/store.mocks';
export {
  mockTauriEnvironment,
  clearTauriEnvironment,
  createMockTauriInvoke,
} from './mocks/tauri.mock';

// Fixtures
export { jobFixtures } from './fixtures/job.fixtures';
export { conversationFixtures } from './fixtures/conversation.fixtures';
export { settingsFixtures } from './fixtures/settings.fixtures';
export { platformFixtures } from './fixtures/platform.fixtures';

// Utilities
export { TestHostComponent, createTestHost } from './utils/test-host.component';
