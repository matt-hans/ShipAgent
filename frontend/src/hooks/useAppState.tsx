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
import type { Job, DataSourceInfo } from '@/types/api';

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
    action?: 'preview' | 'execute' | 'complete' | 'error' | 'elicit';
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
    };
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

export type { ConversationMessage, AppState, ActiveSourceType, ActiveSourceInfo, CachedLocalConfig };
