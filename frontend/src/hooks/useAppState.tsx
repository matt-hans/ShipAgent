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
  PickupResult,
  LocationResult,
  LandedCostResult,
  PaperlessResult,
} from '@/types/api';

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
      | 'pickup_result' | 'location_result' | 'landed_cost_result' | 'paperless_result';
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
    // UPS MCP v2 domain card payloads
    pickup?: PickupResult;
    location?: LocationResult;
    landedCost?: LandedCostResult;
    paperless?: PaperlessResult;
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
