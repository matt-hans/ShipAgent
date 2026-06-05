/**
 * Application settings and credential types.
 */

/** Application settings from the settings singleton. */
export interface AppSettings {
  agent_model: string | null;
  batch_concurrency: number;
  shipper_name: string | null;
  shipper_attention_name: string | null;
  shipper_address1: string | null;
  shipper_address2: string | null;
  shipper_city: string | null;
  shipper_state: string | null;
  shipper_zip: string | null;
  shipper_country: string | null;
  shipper_phone: string | null;
  ups_account_number: string | null;
  ups_environment: string | null;
  onboarding_completed: boolean;
}

/** Credential status (never returns values, only booleans). */
export interface CredentialStatus {
  anthropic_api_key: boolean;
  openai_api_key: boolean;
  gemini_api_key: boolean;
  ups_client_id: boolean;
  ups_client_secret: boolean;
  shopify_access_token: boolean;
  filter_token_secret: boolean;
  shipagent_api_key: boolean;
}

/** Credential key identifiers. */
export type CredentialKey =
  | 'anthropic_api_key'
  | 'openai_api_key'
  | 'gemini_api_key'
  | 'ups_client_id'
  | 'ups_client_secret'
  | 'shopify_access_token'
  | 'filter_token_secret'
  | 'shipagent_api_key';
