/**
 * Global application state management.
 *
 * Manages:
 * - Active job selection
 * - Sidebar state
 * - Connected data source
 * - Conversation history
 */

import * as React from 'react';
import type {
  Job,
  DataSourceInfo,
  BatchPreview,
  PickupPreview,
  PickupResult,
  LocationResult,
  LandedCostResult,
  PaperlessResult,
  PaperlessUploadPrompt,
  TrackingResult,
  ContactSavedResult,
  Contact,
  CustomCommand,
  ChatSessionSummary,
  ProviderConnectionInfo,
  AppSettings,
  CredentialStatus,
  FederatedPlatform,
} from '@/types/api';
import * as api from '@/lib/api';

/** Warning row handling preference, persisted in localStorage. */
type WarningPreference = 'ask' | 'ship-all' | 'skip-warnings';

/** Identifies which data source type is currently active for command routing. */
type ActiveSourceType = 'local' | 'shopify' | null;

/** Descriptive info about the currently active data source. */
interface ActiveSourceInfo {
  type: ActiveSourceType;
  label: string;
  detail: string;
  sourceKind: 'file' | 'database' | 'shopify';
}

/** Cached local source config for one-click reconnect after switching to Shopify. */
interface CachedLocalConfig {
  type: 'csv' | 'excel' | 'database';
  file_path?: string;
}

interface ConversationMessage {
  id: string;
  role: 'user' | 'system';
  content: string;
  timestamp: Date;
  metadata?: {
    jobId?: string;
    action?:
      | 'preview' | 'execute' | 'complete' | 'error' | 'elicit'
      | 'preview_ready'
      | 'pickup_preview' | 'pickup_result' | 'location_result' | 'landed_cost_result'
      | 'paperless_upload_prompt' | 'paperless_result'
      | 'tracking_result' | 'contact_saved';
    preview?: {
      rowCount: number;
      estimatedCost: number;
      warnings: number;
    };
    progress?: {
      total: number;
      processed: number;
      successful: number;
      failed: number;
    };
    elicitation?: {
      questions: Array<{
        id: string;
        question: string;
        options: string[];
      }>;
    };
    completion?: {
      command: string;
      jobName?: string;
      totalRows: number;
      successful: number;
      failed: number;
      totalCostCents: number;
      dutiesTaxesCents?: number;
      internationalCount?: number;
      rowFailures?: Array<{
        rowNumber: number;
        errorCode: string;
        errorMessage: string;
      }>;
    };
    // Batch preview payload (persisted for history replay)
    batchPreview?: BatchPreview;
    // UPS MCP v2 domain card payloads
    pickup?: PickupResult;
    pickupPreview?: PickupPreview;
    location?: LocationResult;
    landedCost?: LandedCostResult;
    paperlessUpload?: PaperlessUploadPrompt;
    paperless?: PaperlessResult;
    tracking?: TrackingResult;
    contactSaved?: ContactSavedResult;
  };
}

interface AppState {
  // Active job being viewed/executed
  activeJob: Job | null;
  setActiveJob: (job: Job | null) => void;

  // Sidebar collapsed state
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;

  // Connected data source
  dataSource: DataSourceInfo | null;
  setDataSource: (source: DataSourceInfo | null) => void;

  // Conversation history
  conversation: ConversationMessage[];
  addMessage: (message: Omit<ConversationMessage, 'id' | 'timestamp'>) => void;
  clearConversation: () => void;

  // Processing state
  isProcessing: boolean;
  setIsProcessing: (processing: boolean) => void;

  // Job list refresh trigger
  jobListVersion: number;
  refreshJobList: () => void;

  // Active data source tracking
  activeSourceType: ActiveSourceType;
  activeSourceInfo: ActiveSourceInfo | null;
  setActiveSourceType: (type: ActiveSourceType) => void;
  setActiveSourceInfo: (info: ActiveSourceInfo | null) => void;

  // Cached local config for reconnect after switching to Shopify
  cachedLocalConfig: CachedLocalConfig | null;
  setCachedLocalConfig: (config: CachedLocalConfig | null) => void;

  // Warning row handling preference
  warningPreference: WarningPreference;
  setWarningPreference: (pref: WarningPreference) => void;

  // Conversation session ID for agent-driven flow
  conversationSessionId: string | null;
  setConversationSessionId: (id: string | null) => void;

  // Interactive single-shipment mode toggle
  interactiveShipping: boolean;
  setInteractiveShipping: (enabled: boolean) => void;

  // Write-back toggle: controls whether tracking numbers are written back to source
  writeBackEnabled: boolean;
  setWriteBackEnabled: (enabled: boolean) => void;

  // Lock flag: disables the toggle while a session reset or creation is in-flight
  isToggleLocked: boolean;
  setIsToggleLocked: (locked: boolean) => void;

  // Contact book state (hydrated on mount, refreshed after mutations)
  contacts: Contact[];
  setContacts: (contacts: Contact[]) => void;
  refreshContacts: () => Promise<void>;

  // Custom commands state (hydrated on mount, refreshed after mutations)
  customCommands: CustomCommand[];
  setCustomCommands: (commands: CustomCommand[]) => void;
  refreshCommands: () => Promise<void>;

  // Settings flyout visibility
  settingsFlyoutOpen: boolean;
  setSettingsFlyoutOpen: (open: boolean) => void;

  // Chat history flyout visibility
  chatHistoryFlyoutOpen: boolean;
  setChatHistoryFlyoutOpen: (open: boolean) => void;

  // Pending chat message — set by sidebar to auto-inject into the chat agent
  pendingChatMessage: string | null;
  setPendingChatMessage: (msg: string | null) => void;

  // Chat session history for sidebar
  chatSessions: ChatSessionSummary[];
  setChatSessions: (sessions: ChatSessionSummary[]) => void;
  chatSessionsVersion: number;
  refreshChatSessions: () => void;
  deleteChatSession: (sessionId: string) => Promise<void>;
  deleteAllChatSessions: () => Promise<void>;
  activeSessionTitle: string | null;
  setActiveSessionTitle: (title: string | null) => void;

  // Provider connections state
  providerConnections: ProviderConnectionInfo[];
  providerConnectionsLoading: boolean;
  providerConnectionsVersion: number;
  refreshProviderConnections: () => void;

  // Federated platforms state
  federatedPlatforms: FederatedPlatform[];
  federatedPlatformsLoading: boolean;
  federatedPlatformsVersion: number;
  refreshFederatedPlatforms: () => void;
  togglePlatformActive: (platformId: string) => Promise<void>;

  // App settings + onboarding state
  appSettings: AppSettings | null;
  appSettingsLoading: boolean;
  appSettingsError: string | null;
  credentialStatus: CredentialStatus | null;
  refreshAppSettings: () => Promise<void>;
  refreshCredentialStatus: () => Promise<void>;
}

const AppStateContext = React.createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [activeJob, setActiveJob] = React.useState<Job | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);
  const [dataSource, setDataSource] = React.useState<DataSourceInfo | null>(null);
  const [conversation, setConversation] = React.useState<ConversationMessage[]>([]);
  const [isProcessing, setIsProcessing] = React.useState(false);
  const [jobListVersion, setJobListVersion] = React.useState(0);
  const [activeSourceType, setActiveSourceType] = React.useState<ActiveSourceType>(null);
  const [activeSourceInfo, setActiveSourceInfo] = React.useState<ActiveSourceInfo | null>(null);
  const [cachedLocalConfig, setCachedLocalConfig] = React.useState<CachedLocalConfig | null>(null);
  const [conversationSessionId, setConversationSessionId] = React.useState<string | null>(null);
  const [warningPreference, setWarningPreferenceState] = React.useState<WarningPreference>(() => {
    const stored = localStorage.getItem('shipagent_warning_preference');
    return (stored === 'ship-all' || stored === 'skip-warnings') ? stored : 'ask';
  });

  const setWarningPreference = React.useCallback((pref: WarningPreference) => {
    setWarningPreferenceState(pref);
    localStorage.setItem('shipagent_warning_preference', pref);
  }, []);

  const [interactiveShipping, setInteractiveShippingState] = React.useState<boolean>(() => {
    return localStorage.getItem('shipagent_interactive_shipping') === 'true';
  });

  const setInteractiveShipping = React.useCallback((enabled: boolean) => {
    setInteractiveShippingState(enabled);
    localStorage.setItem('shipagent_interactive_shipping', String(enabled));
  }, []);

  const [writeBackEnabled, setWriteBackEnabledState] = React.useState<boolean>(() => {
    return localStorage.getItem('shipagent_write_back') !== 'false';
  });

  const setWriteBackEnabled = React.useCallback((enabled: boolean) => {
    setWriteBackEnabledState(enabled);
    localStorage.setItem('shipagent_write_back', String(enabled));
  }, []);

  const [isToggleLocked, setIsToggleLocked] = React.useState(false);

  // Contact book state
  const [contacts, setContacts] = React.useState<Contact[]>([]);

  // Custom commands state
  const [customCommands, setCustomCommands] = React.useState<CustomCommand[]>([]);

  // Settings flyout state
  const [settingsFlyoutOpen, setSettingsFlyoutOpen] = React.useState(false);

  // Chat history flyout state
  const [chatHistoryFlyoutOpen, setChatHistoryFlyoutOpen] = React.useState(false);

  // Pending chat message (sidebar → chat bridge)
  const [pendingChatMessage, setPendingChatMessage] = React.useState<string | null>(null);

  // Chat session history state
  const [chatSessions, setChatSessions] = React.useState<ChatSessionSummary[]>([]);
  const [chatSessionsVersion, setChatSessionsVersion] = React.useState(0);
  const [activeSessionTitle, setActiveSessionTitle] = React.useState<string | null>(null);

  const refreshChatSessions = React.useCallback(() => {
    setChatSessionsVersion((v) => v + 1);
  }, []);

  const deleteChatSession = React.useCallback(async (sessionId: string) => {
    // Delete in DB first, then update state to match
    await api.deleteConversation(sessionId);
    setChatSessions((prev) => {
      const next = prev.filter((s) => s.id !== sessionId);
      return next;
    });
  }, []);

  const deleteAllChatSessions = React.useCallback(async () => {
    // Optimistic update — clear all sessions immediately
    setChatSessions([]);
    try {
      await api.deleteAllConversations();
    } catch (err) {
      console.error('Failed to delete all sessions:', err);
      // Re-fetch to restore accurate state on failure
      setChatSessionsVersion((v) => v + 1);
    }
  }, []);

  // App settings + onboarding state
  const [appSettings, setAppSettings] = React.useState<AppSettings | null>(null);
  const [appSettingsLoading, setAppSettingsLoading] = React.useState(true);
  const [appSettingsError, setAppSettingsError] = React.useState<string | null>(null);
  const [credentialStatus, setCredentialStatus] = React.useState<CredentialStatus | null>(null);

  const refreshAppSettings = React.useCallback(async () => {
    try {
      setAppSettingsError(null);
      const settings = await api.getSettings();
      setAppSettings(settings);
    } catch (error: any) {
      const msg = error?.message || 'Failed to fetch app settings';
      console.error('Failed to fetch app settings:', error);
      setAppSettingsError(msg);
    }
  }, []);

  const refreshCredentialStatus = React.useCallback(async () => {
    try {
      const status = await api.getCredentialStatus();
      setCredentialStatus(status);
    } catch (error) {
      console.error('Failed to fetch credential status:', error);
    }
  }, []);

  // Fetch settings on mount
  React.useEffect(() => {
    setAppSettingsLoading(true);
    Promise.all([
      api.getSettings(),
      api.getCredentialStatus(),
    ])
      .then(([settings, creds]) => {
        setAppSettings(settings);
        setCredentialStatus(creds);
      })
      .catch((error) => {
        const msg = error?.message || 'Failed to fetch initial settings';
        console.error('Failed to fetch initial settings:', error);
        setAppSettingsError(msg);
      })
      .finally(() => {
        setAppSettingsLoading(false);
      });
  }, []);

  // Provider connections state
  const [providerConnections, setProviderConnections] = React.useState<ProviderConnectionInfo[]>([]);
  const [providerConnectionsLoading, setProviderConnectionsLoading] = React.useState(false);
  const [providerConnectionsVersion, setProviderConnectionsVersion] = React.useState(0);

  const refreshProviderConnections = React.useCallback(() => {
    setProviderConnectionsVersion((v) => v + 1);
  }, []);

  // Fetch provider connections on mount and when version changes
  React.useEffect(() => {
    let cancelled = false;
    setProviderConnectionsLoading(true);
    api.listProviderConnections()
      .then((connections) => {
        if (!cancelled) {
          setProviderConnections(connections);
        }
      })
      .catch((error) => {
        console.error('Failed to fetch provider connections:', error);
      })
      .finally(() => {
        if (!cancelled) {
          setProviderConnectionsLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [providerConnectionsVersion]);

  // Federated platforms state
  const [federatedPlatforms, setFederatedPlatforms] = React.useState<FederatedPlatform[]>([]);
  const [federatedPlatformsLoading, setFederatedPlatformsLoading] = React.useState(true);
  const [federatedPlatformsVersion, setFederatedPlatformsVersion] = React.useState(0);

  const refreshFederatedPlatforms = React.useCallback(() => {
    setFederatedPlatformsVersion((v) => v + 1);
  }, []);

  // Fetch federated platforms on mount and when version changes
  React.useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setFederatedPlatformsLoading(true);
      try {
        const result = await api.listFederatedPlatforms();
        if (!cancelled && result.success) {
          setFederatedPlatforms(result.platforms);
        }
      } catch (err) {
        console.error('Failed to load federated platforms:', err);
      } finally {
        if (!cancelled) setFederatedPlatformsLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [federatedPlatformsVersion]);

  const togglePlatformActive = React.useCallback(async (platformId: string) => {
    const platform = federatedPlatforms.find((p) => p.platform_id === platformId);
    if (!platform) return;

    // Toggling OFF — just remove from active set
    if (platform.is_active) {
      const newActiveIds = federatedPlatforms
        .filter((p) => p.is_active && p.platform_id !== platformId)
        .map((p) => p.platform_id);
      await api.setActivePlatforms(newActiveIds);
      refreshFederatedPlatforms();
      return;
    }

    // Toggling ON — deterministic compatibility flow:
    // always activate/import first so active implies query-ready source.
    const activation = await api.activatePlatformCompat(platformId);
    if (!activation.success) {
      const code = activation.error_code ? `[${activation.error_code}] ` : '';
      throw new Error(`${code}${activation.error || 'Platform activation failed'}`);
    }

    const newActiveIds = federatedPlatforms
      .filter((p) => p.is_active)
      .map((p) => p.platform_id)
      .concat(platformId);
    const setActiveResult = await api.setActivePlatforms(newActiveIds);
    if (!setActiveResult.success) {
      throw new Error(setActiveResult.error || 'Failed to mark platform active');
    }
    refreshFederatedPlatforms();
  }, [federatedPlatforms, refreshFederatedPlatforms]);

  // Refresh contacts from API
  const refreshContacts = React.useCallback(async () => {
    try {
      const response = await api.listContacts({ limit: 100 });
      setContacts(response.contacts);
    } catch (error) {
      console.error('Failed to refresh contacts:', error);
    }
  }, []);

  // Refresh commands from API
  const refreshCommands = React.useCallback(async () => {
    try {
      const response = await api.listCommands({ limit: 100 });
      setCustomCommands(response.commands);
    } catch (error) {
      console.error('Failed to refresh commands:', error);
    }
  }, []);

  // Hydrate contacts and commands on mount
  React.useEffect(() => {
    refreshContacts();
    refreshCommands();
  }, [refreshContacts, refreshCommands]);

  const refreshJobList = React.useCallback(() => {
    setJobListVersion((v) => v + 1);
  }, []);

  const addMessage = React.useCallback(
    (message: Omit<ConversationMessage, 'id' | 'timestamp'>) => {
      const newMessage: ConversationMessage = {
        ...message,
        id: crypto.randomUUID(),
        timestamp: new Date(),
      };
      setConversation((prev) => [...prev, newMessage]);
    },
    []
  );

  const clearConversation = React.useCallback(() => {
    setConversation([]);
  }, []);

  const value: AppState = {
    activeJob,
    setActiveJob,
    sidebarCollapsed,
    setSidebarCollapsed,
    dataSource,
    setDataSource,
    conversation,
    addMessage,
    clearConversation,
    isProcessing,
    setIsProcessing,
    jobListVersion,
    refreshJobList,
    activeSourceType,
    activeSourceInfo,
    setActiveSourceType,
    setActiveSourceInfo,
    cachedLocalConfig,
    setCachedLocalConfig,
    warningPreference,
    setWarningPreference,
    conversationSessionId,
    setConversationSessionId,
    interactiveShipping,
    setInteractiveShipping,
    writeBackEnabled,
    setWriteBackEnabled,
    isToggleLocked,
    setIsToggleLocked,
    contacts,
    setContacts,
    refreshContacts,
    customCommands,
    setCustomCommands,
    refreshCommands,
    settingsFlyoutOpen,
    setSettingsFlyoutOpen,
    chatHistoryFlyoutOpen,
    setChatHistoryFlyoutOpen,
    pendingChatMessage,
    setPendingChatMessage,
    chatSessions,
    setChatSessions,
    chatSessionsVersion,
    refreshChatSessions,
    deleteChatSession,
    deleteAllChatSessions,
    activeSessionTitle,
    setActiveSessionTitle,
    providerConnections,
    providerConnectionsLoading,
    providerConnectionsVersion,
    refreshProviderConnections,
    federatedPlatforms,
    federatedPlatformsLoading,
    federatedPlatformsVersion,
    refreshFederatedPlatforms,
    togglePlatformActive,
    appSettings,
    appSettingsLoading,
    appSettingsError,
    credentialStatus,
    refreshAppSettings,
    refreshCredentialStatus,
  };

  return (
    <AppStateContext.Provider value={value}>
      {children}
    </AppStateContext.Provider>
  );
}

export function useAppState() {
  const context = React.useContext(AppStateContext);
  if (!context) {
    throw new Error('useAppState must be used within AppStateProvider');
  }
  return context;
}

export type { ConversationMessage, AppState, ActiveSourceType, ActiveSourceInfo, CachedLocalConfig, WarningPreference };
