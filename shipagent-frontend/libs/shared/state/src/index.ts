// @shipagent/shared-state — All 8 NgRx SignalStores for application state

// UI flags
export { AppStore } from './app.store';
export type { AppState } from './app.store';

// Active conversation session
export { ConversationStore } from './conversation.store';
export type { ConversationState } from './conversation.store';

// Batch job tracking
export { JobStore } from './job.store';
export type { JobState } from './job.store';

// Data source connection
export { DataSourceStore } from './data-source.store';
export type { DataSourceState, SourceType, LocalSourceConfig } from './data-source.store';

// Application settings
export { SettingsStore } from './settings.store';
export type { SettingsState } from './settings.store';

// Address book contacts
export { ContactsStore } from './contacts.store';
export type { ContactsState } from './contacts.store';

// Custom slash commands
export { CommandsStore } from './commands.store';
export type { CommandsState } from './commands.store';

// External platform connections
export { PlatformsStore } from './platforms.store';
export type { PlatformsState } from './platforms.store';
