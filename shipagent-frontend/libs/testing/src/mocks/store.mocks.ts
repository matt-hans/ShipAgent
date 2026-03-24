/**
 * Factory functions for creating pre-populated NgRx SignalStore states.
 * Used in tests that need a store with realistic initial data.
 */

import type {
  Job,
  JobSummary,
  AppSettings,
  Contact,
  CustomCommand,
  ChatSessionSummary,
  PlatformConnection,
} from '@shipagent/shared-types';

// ============================================================
// CONVERSATION STORE STATE
// ============================================================

export interface MockConversationStoreState {
  sessionId: string | null;
  isInteractiveMode: boolean;
  isConnected: boolean;
  isStreaming: boolean;
  messages: Array<{ id: string; role: string; content: string; timestamp: string }>;
  chatSessions: ChatSessionSummary[];
}

/**
 * Create a default conversation store state.
 */
export function createMockConversationState(
  overrides: Partial<MockConversationStoreState> = {},
): MockConversationStoreState {
  return {
    sessionId: null,
    isInteractiveMode: false,
    isConnected: false,
    isStreaming: false,
    messages: [],
    chatSessions: [],
    ...overrides,
  };
}

// ============================================================
// JOB STORE STATE
// ============================================================

export interface MockJobStoreState {
  jobs: JobSummary[];
  selectedJobId: string | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * Create a default job store state.
 */
export function createMockJobState(
  overrides: Partial<MockJobStoreState> = {},
): MockJobStoreState {
  return {
    jobs: [],
    selectedJobId: null,
    isLoading: false,
    error: null,
    ...overrides,
  };
}

// ============================================================
// DATA SOURCE STORE STATE
// ============================================================

export interface MockDataSourceStoreState {
  isConnected: boolean;
  sourceType: string | null;
  filePath: string | null;
  rowCount: number | null;
  label: string | null;
}

/**
 * Create a default data source store state.
 */
export function createMockDataSourceState(
  overrides: Partial<MockDataSourceStoreState> = {},
): MockDataSourceStoreState {
  return {
    isConnected: false,
    sourceType: null,
    filePath: null,
    rowCount: null,
    label: null,
    ...overrides,
  };
}

// ============================================================
// SETTINGS STORE STATE
// ============================================================

export interface MockSettingsStoreState {
  settings: AppSettings | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * Create a default settings store state.
 */
export function createMockSettingsState(
  overrides: Partial<MockSettingsStoreState> = {},
): MockSettingsStoreState {
  return {
    settings: null,
    isLoading: false,
    error: null,
    ...overrides,
  };
}

// ============================================================
// CONTACTS STORE STATE
// ============================================================

export interface MockContactsStoreState {
  contacts: Contact[];
  isLoading: boolean;
  error: string | null;
}

/**
 * Create a default contacts store state.
 */
export function createMockContactsState(
  overrides: Partial<MockContactsStoreState> = {},
): MockContactsStoreState {
  return {
    contacts: [],
    isLoading: false,
    error: null,
    ...overrides,
  };
}

// ============================================================
// COMMANDS STORE STATE
// ============================================================

export interface MockCommandsStoreState {
  commands: CustomCommand[];
  isLoading: boolean;
  error: string | null;
}

/**
 * Create a default commands store state.
 */
export function createMockCommandsState(
  overrides: Partial<MockCommandsStoreState> = {},
): MockCommandsStoreState {
  return {
    commands: [],
    isLoading: false,
    error: null,
    ...overrides,
  };
}

// ============================================================
// PLATFORMS STORE STATE
// ============================================================

export interface MockPlatformsStoreState {
  connections: PlatformConnection[];
  isLoading: boolean;
  error: string | null;
}

/**
 * Create a default platforms store state.
 */
export function createMockPlatformsState(
  overrides: Partial<MockPlatformsStoreState> = {},
): MockPlatformsStoreState {
  return {
    connections: [],
    isLoading: false,
    error: null,
    ...overrides,
  };
}

// ============================================================
// APP STORE STATE
// ============================================================

export interface MockAppStoreState {
  isOnboarded: boolean;
  isSidebarOpen: boolean;
  activePanel: 'data-source' | 'job-history' | 'chat-sessions' | null;
}

/**
 * Create a default app store state.
 */
export function createMockAppState(
  overrides: Partial<MockAppStoreState> = {},
): MockAppStoreState {
  return {
    isOnboarded: false,
    isSidebarOpen: true,
    activePanel: null,
    ...overrides,
  };
}
