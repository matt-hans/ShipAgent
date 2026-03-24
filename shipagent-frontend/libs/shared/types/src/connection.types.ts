/**
 * Provider connection types for the /connections/ API domain.
 * Manages UPS, Shopify, Amazon, and other provider credentials.
 */

export type ProviderType = 'ups' | 'shopify' | 'amazon';

/**
 * Provider connection status.
 * Phase 1: only 'configured', 'disconnected', 'needs_reconnect' are actively produced.
 * 'connected', 'validating', 'error' are reserved for Phase 2 live validation.
 */
export type ProviderConnectionStatus =
  | 'configured'
  | 'validating'
  | 'connected'
  | 'disconnected'
  | 'error'
  | 'needs_reconnect';

export type ProviderAuthMode =
  | 'client_credentials'
  | 'legacy_token'
  | 'client_credentials_shopify'
  | 'sp_api';

/** Full provider connection record (no credentials exposed). */
export interface ProviderConnectionInfo {
  id: string;
  connection_key: string;
  provider: ProviderType;
  display_name: string;
  auth_mode: ProviderAuthMode;
  environment: string | null;
  status: ProviderConnectionStatus;
  metadata: Record<string, unknown>;
  last_validated_at: string | null;
  last_error_code: string | null;
  error_message: string | null;
  runtime_usable: boolean;
  runtime_reason: string | null;
  created_at: string;
  updated_at: string;
}

/** Request to save/overwrite provider credentials. */
export interface SaveProviderRequest {
  auth_mode: ProviderAuthMode;
  credentials: Record<string, string>;
  metadata: Record<string, unknown>;
  display_name: string;
  environment?: string;
}

/** Result of credential validation against the real provider API. */
export interface ValidateConnectionResult {
  valid: boolean;
  status: string;
  message: string;
  details?: Record<string, unknown>;
}

/** Response from listing provider connections. */
export type ListProviderConnectionsResponse = ProviderConnectionInfo[];
