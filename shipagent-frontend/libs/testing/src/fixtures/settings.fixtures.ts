/**
 * Settings and credential test fixtures.
 */

import type { AppSettings, CredentialStatus } from '@shipagent/shared-types';

export const settingsFixtures = {
  /** Fully configured app settings. */
  fullSettings: (): AppSettings => ({
    agent_model: 'claude-haiku-4-5',
    batch_concurrency: 5,
    shipper_name: 'John Doe',
    shipper_attention_name: null,
    shipper_address1: '100 Shipping Lane',
    shipper_address2: null,
    shipper_city: 'Los Angeles',
    shipper_state: 'CA',
    shipper_zip: '90001',
    shipper_country: 'US',
    shipper_phone: '555-0100',
    ups_account_number: 'A1B2C3',
    ups_environment: 'sandbox',
    onboarding_completed: true,
  }),

  /** Minimal settings — onboarding not yet completed. */
  freshSettings: (): AppSettings => ({
    agent_model: null,
    batch_concurrency: 5,
    shipper_name: null,
    shipper_attention_name: null,
    shipper_address1: null,
    shipper_address2: null,
    shipper_city: null,
    shipper_state: null,
    shipper_zip: null,
    shipper_country: null,
    shipper_phone: null,
    ups_account_number: null,
    ups_environment: null,
    onboarding_completed: false,
  }),

  /** All credentials configured. */
  allCredentials: (): CredentialStatus => ({
    anthropic_api_key: true,
    openai_api_key: true,
    gemini_api_key: true,
    ups_client_id: true,
    ups_client_secret: true,
    shopify_access_token: true,
    filter_token_secret: true,
    shipagent_api_key: false,
  }),

  /** No credentials configured. */
  noCredentials: (): CredentialStatus => ({
    anthropic_api_key: false,
    openai_api_key: false,
    gemini_api_key: false,
    ups_client_id: false,
    ups_client_secret: false,
    shopify_access_token: false,
    filter_token_secret: false,
    shipagent_api_key: false,
  }),

  /** Only Anthropic key configured (minimum for operation). */
  anthropicOnlyCredentials: (): CredentialStatus => ({
    anthropic_api_key: true,
    openai_api_key: false,
    gemini_api_key: false,
    ups_client_id: false,
    ups_client_secret: false,
    shopify_access_token: false,
    filter_token_secret: false,
    shipagent_api_key: false,
  }),
};
