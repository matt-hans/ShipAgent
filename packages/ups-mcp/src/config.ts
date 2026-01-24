/**
 * UPS MCP Configuration Module
 *
 * Handles environment variable validation and configuration management.
 * Per CONTEXT.md Decision 1:
 * - Fail fast on missing credentials
 * - Single account only
 * - Sandbox environment only
 */

/**
 * Configuration interface for UPS MCP server
 */
export interface Config {
  /** UPS OAuth Client ID */
  clientId: string;
  /** UPS OAuth Client Secret */
  clientSecret: string;
  /** UPS Shipper Account Number */
  accountNumber: string;
  /** Directory for saving generated labels */
  labelsOutputDir: string;
  /** UPS API base URL (sandbox only for MVP) */
  baseUrl: string;
}

/**
 * Required environment variables for UPS MCP
 */
const REQUIRED_ENV_VARS = [
  "UPS_CLIENT_ID",
  "UPS_CLIENT_SECRET",
  "UPS_ACCOUNT_NUMBER",
] as const;

/**
 * UPS sandbox environment base URL
 * Per CONTEXT.md: production support is out of scope for MVP
 */
const UPS_SANDBOX_BASE_URL = "https://wwwcie.ups.com/api";

/**
 * Default directory for label output
 */
const DEFAULT_LABELS_OUTPUT_DIR = "./labels";

/**
 * Validates that all required environment variables are present.
 * Throws an error listing all missing variables if any are absent.
 *
 * @returns Config object with validated values
 * @throws Error if any required environment variable is missing
 */
export function validateConfig(): Config {
  const missing: string[] = [];

  for (const envVar of REQUIRED_ENV_VARS) {
    if (!process.env[envVar]) {
      missing.push(envVar);
    }
  }

  if (missing.length > 0) {
    throw new Error(
      `UPS MCP: Missing required environment variables: ${missing.join(", ")}\n` +
        `Please set the following environment variables:\n` +
        missing.map((v) => `  - ${v}`).join("\n")
    );
  }

  return {
    clientId: process.env.UPS_CLIENT_ID!,
    clientSecret: process.env.UPS_CLIENT_SECRET!,
    accountNumber: process.env.UPS_ACCOUNT_NUMBER!,
    labelsOutputDir: process.env.LABELS_OUTPUT_DIR || DEFAULT_LABELS_OUTPUT_DIR,
    baseUrl: UPS_SANDBOX_BASE_URL,
  };
}

/**
 * Singleton configuration instance
 * Validates on first access, fails fast if credentials are missing
 */
export const config = validateConfig();
