/**
 * UPS OAuth Token Manager
 *
 * Manages OAuth 2.0 client_credentials flow for UPS API authentication.
 * - Acquires tokens from UPS OAuth endpoint
 * - Caches tokens and reuses until near expiry
 * - Automatically refreshes with 1-minute buffer before expiry
 * - Clears cache on auth failures
 */

import { UpsAuthError } from "../client/errors.js";

/**
 * Response from UPS OAuth token endpoint
 */
interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  issued_at?: string;
}

/**
 * Default token URL for UPS sandbox environment
 */
const UPS_SANDBOX_TOKEN_URL = "https://wwwcie.ups.com/security/v1/oauth/token";

/**
 * Buffer time in milliseconds before token expiry to trigger refresh
 * Set to 60 seconds to ensure we don't use tokens right at their expiry
 */
const EXPIRY_BUFFER_MS = 60_000;

/**
 * Manages OAuth tokens for UPS API authentication
 *
 * Usage:
 * ```typescript
 * const authManager = new UpsAuthManager(clientId, clientSecret);
 * const token = await authManager.getToken();
 * // token is cached and reused until near expiry
 * ```
 */
export class UpsAuthManager {
  private token: string | null = null;
  private expiresAt: number = 0;

  /**
   * Creates a new UpsAuthManager
   *
   * @param clientId - UPS OAuth Client ID
   * @param clientSecret - UPS OAuth Client Secret
   * @param tokenUrl - OAuth token endpoint URL (defaults to sandbox)
   */
  constructor(
    private readonly clientId: string,
    private readonly clientSecret: string,
    private readonly tokenUrl: string = UPS_SANDBOX_TOKEN_URL
  ) {}

  /**
   * Gets a valid OAuth token, refreshing if necessary
   *
   * Returns cached token if still valid (with 60-second buffer).
   * Otherwise refreshes the token from UPS OAuth endpoint.
   *
   * @returns Promise resolving to valid access token
   * @throws UpsAuthError if token refresh fails
   */
  async getToken(): Promise<string> {
    // Return cached token if valid (with buffer before expiry)
    if (this.token && Date.now() < this.expiresAt - EXPIRY_BUFFER_MS) {
      return this.token;
    }
    return this.refreshToken();
  }

  /**
   * Refreshes the OAuth token from UPS endpoint
   *
   * @returns Promise resolving to new access token
   * @throws UpsAuthError if token refresh fails
   */
  private async refreshToken(): Promise<string> {
    // Build Basic auth header: base64(clientId:clientSecret)
    const credentials = Buffer.from(
      `${this.clientId}:${this.clientSecret}`
    ).toString("base64");

    try {
      const response = await fetch(this.tokenUrl, {
        method: "POST",
        headers: {
          Authorization: `Basic ${credentials}`,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: "grant_type=client_credentials",
      });

      if (!response.ok) {
        // Clear token on auth failure
        this.clearToken();
        const statusText = response.statusText || "Unknown error";
        throw new UpsAuthError(
          `Token refresh failed: ${response.status} ${statusText}`
        );
      }

      const data: TokenResponse = await response.json();

      // Cache the token
      this.token = data.access_token;
      // Calculate expiry time: current time + expires_in seconds
      this.expiresAt = Date.now() + data.expires_in * 1000;

      return this.token;
    } catch (error) {
      // Clear token on any error
      this.clearToken();

      // Re-throw UpsAuthError as-is
      if (error instanceof UpsAuthError) {
        throw error;
      }

      // Wrap other errors
      throw new UpsAuthError(
        "Token refresh failed due to network error",
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Clears the cached token
   *
   * Use when token is known to be invalid (e.g., after 401 response).
   */
  clearToken(): void {
    this.token = null;
    this.expiresAt = 0;
  }

  /**
   * Checks if there is a cached token (regardless of validity)
   *
   * Useful for testing.
   */
  hasToken(): boolean {
    return this.token !== null;
  }
}
