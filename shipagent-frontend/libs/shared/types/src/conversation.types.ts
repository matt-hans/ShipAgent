/**
 * Conversation session and SSE streaming types.
 */

/** Agent event types streamed via SSE. */
export type AgentEventType =
  | 'agent_thinking'
  | 'tool_call'
  | 'tool_result'
  | 'agent_message'
  | 'agent_message_delta'
  | 'preview_partial'
  | 'preview_ready'
  | 'pickup_preview'
  | 'pickup_result'
  | 'location_result'
  | 'landed_cost_result'
  | 'paperless_upload_prompt'
  | 'paperless_result'
  | 'tracking_result'
  | 'contact_saved'
  | 'confirmation_needed'
  | 'execution_progress'
  | 'completion'
  | 'error'
  | 'done'
  | 'ping';

/** Base agent event from SSE stream. */
export interface AgentEvent {
  event: AgentEventType;
  data: Record<string, unknown>;
}

/** Create conversation response. */
export interface CreateConversationResponse {
  session_id: string;
  interactive_shipping: boolean;
}

/** Send message response. */
export interface SendMessageResponse {
  status: string;
  session_id: string;
}

/** Data source context persisted with a session for restoration. */
export interface DataSourceContext {
  type: 'local' | 'shopify' | 'amazon' | null;
  source_type: string | null;
  saved_source_id: string | null;
  file_path: string | null;
  label: string | null;
  row_count: number | null;
}

/** Session context snapshot persisted to the database. */
export interface SessionContext {
  data_source: DataSourceContext | null;
}

/** Lightweight session summary for sidebar listing. */
export interface ChatSessionSummary {
  id: string;
  title: string | null;
  mode: 'batch' | 'interactive';
  context_data?: SessionContext | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

/** Persisted message for history display. */
export interface PersistedMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  message_type: 'text' | 'system_artifact' | 'error';
  content: string;
  metadata: Record<string, unknown> | null;
  sequence: number;
  created_at: string;
}

/** Full session with messages for resume. */
export interface SessionDetail {
  session: ChatSessionSummary;
  messages: PersistedMessage[];
}

/**
 * Warning row handling preference for the conversation store.
 * Persisted to localStorage via withStorageSync.
 */
export type WarningPreference = 'ask' | 'ship-all' | 'skip-warnings';

/**
 * In-memory conversation message for the active session display.
 * Note: PersistedMessage is the DB-backed version; ConversationMessage is the live UI model.
 */
export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}
