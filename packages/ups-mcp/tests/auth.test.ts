/**
 * Tests for UpsAuthManager
 *
 * Verifies OAuth token acquisition, caching, and error handling.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { UpsAuthManager } from "../src/auth/manager.js";
import { UpsAuthError } from "../src/client/errors.js";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("UpsAuthManager", () => {
  const clientId = "test-client-id";
  const clientSecret = "test-client-secret";
  const tokenUrl = "https://test.ups.com/oauth/token";

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /**
   * Helper to create a mock successful token response
   */
  function mockSuccessResponse(expiresIn = 14399): Response {
    return new Response(
      JSON.stringify({
        access_token: "test-access-token",
        token_type: "Bearer",
        expires_in: expiresIn,
        issued_at: Date.now().toString(),
      }),
      { status: 200, statusText: "OK" }
    );
  }

  /**
   * Helper to create a mock error response
   */
  function mockErrorResponse(status: number, statusText: string): Response {
    return new Response(JSON.stringify({ error: "invalid_client" }), {
      status,
      statusText,
    });
  }

  describe("getToken", () => {
    it("should acquire a new token when none is cached", async () => {
      mockFetch.mockResolvedValueOnce(mockSuccessResponse());

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);
      const token = await manager.getToken();

      expect(token).toBe("test-access-token");
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledWith(tokenUrl, {
        method: "POST",
        headers: {
          Authorization: expect.stringContaining("Basic "),
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: "grant_type=client_credentials",
      });
    });

    it("should return cached token when still valid", async () => {
      mockFetch.mockResolvedValueOnce(mockSuccessResponse(3600)); // 1 hour

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);

      // First call acquires token
      const token1 = await manager.getToken();
      expect(token1).toBe("test-access-token");
      expect(mockFetch).toHaveBeenCalledTimes(1);

      // Advance time by 30 minutes (still valid with 60s buffer)
      vi.advanceTimersByTime(30 * 60 * 1000);

      // Second call should use cache
      const token2 = await manager.getToken();
      expect(token2).toBe("test-access-token");
      expect(mockFetch).toHaveBeenCalledTimes(1); // No new fetch
    });

    it("should refresh token when within 60 seconds of expiry", async () => {
      mockFetch
        .mockResolvedValueOnce(mockSuccessResponse(120)) // 2 minutes
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              access_token: "refreshed-token",
              token_type: "Bearer",
              expires_in: 3600,
            }),
            { status: 200 }
          )
        );

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);

      // First call acquires token
      const token1 = await manager.getToken();
      expect(token1).toBe("test-access-token");

      // Advance time to within 60 seconds of expiry
      vi.advanceTimersByTime(70 * 1000); // 70 seconds (50s left, within buffer)

      // Second call should refresh
      const token2 = await manager.getToken();
      expect(token2).toBe("refreshed-token");
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it("should refresh token when fully expired", async () => {
      mockFetch
        .mockResolvedValueOnce(mockSuccessResponse(60)) // 1 minute
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              access_token: "new-token",
              token_type: "Bearer",
              expires_in: 3600,
            }),
            { status: 200 }
          )
        );

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);

      // First call acquires token
      await manager.getToken();

      // Advance time past expiry
      vi.advanceTimersByTime(120 * 1000); // 2 minutes

      // Should refresh
      const token = await manager.getToken();
      expect(token).toBe("new-token");
    });
  });

  describe("error handling", () => {
    it("should throw UpsAuthError on 401 response", async () => {
      mockFetch.mockResolvedValueOnce(mockErrorResponse(401, "Unauthorized"));

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);

      try {
        await manager.getToken();
        expect.fail("Should have thrown UpsAuthError");
      } catch (error) {
        expect(error).toBeInstanceOf(UpsAuthError);
        expect((error as Error).message).toMatch(/Token refresh failed: 401/);
      }
    });

    it("should throw UpsAuthError on 403 response", async () => {
      mockFetch.mockResolvedValueOnce(mockErrorResponse(403, "Forbidden"));

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);

      await expect(manager.getToken()).rejects.toThrow(UpsAuthError);
    });

    it("should throw UpsAuthError on network error", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network error"));

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);

      try {
        await manager.getToken();
        expect.fail("Should have thrown UpsAuthError");
      } catch (error) {
        expect(error).toBeInstanceOf(UpsAuthError);
        expect((error as Error).message).toMatch(/network error/i);
      }
    });

    it("should clear cached token on auth failure", async () => {
      // First successful auth
      mockFetch.mockResolvedValueOnce(mockSuccessResponse(60));

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);
      await manager.getToken();
      expect(manager.hasToken()).toBe(true);

      // Advance past expiry
      vi.advanceTimersByTime(120 * 1000);

      // Failed refresh
      mockFetch.mockResolvedValueOnce(mockErrorResponse(401, "Unauthorized"));

      await expect(manager.getToken()).rejects.toThrow(UpsAuthError);
      expect(manager.hasToken()).toBe(false);
    });
  });

  describe("clearToken", () => {
    it("should remove cached token", async () => {
      mockFetch.mockResolvedValueOnce(mockSuccessResponse());

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);
      await manager.getToken();
      expect(manager.hasToken()).toBe(true);

      manager.clearToken();
      expect(manager.hasToken()).toBe(false);
    });

    it("should force refresh on next getToken call", async () => {
      mockFetch
        .mockResolvedValueOnce(mockSuccessResponse())
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              access_token: "second-token",
              token_type: "Bearer",
              expires_in: 3600,
            }),
            { status: 200 }
          )
        );

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);

      // First token
      const token1 = await manager.getToken();
      expect(token1).toBe("test-access-token");

      // Clear and get new token
      manager.clearToken();
      const token2 = await manager.getToken();
      expect(token2).toBe("second-token");
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  describe("authentication header", () => {
    it("should encode credentials as base64", async () => {
      mockFetch.mockResolvedValueOnce(mockSuccessResponse());

      const manager = new UpsAuthManager(clientId, clientSecret, tokenUrl);
      await manager.getToken();

      const expectedAuth = Buffer.from(
        `${clientId}:${clientSecret}`
      ).toString("base64");

      expect(mockFetch).toHaveBeenCalledWith(
        tokenUrl,
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: `Basic ${expectedAuth}`,
          }),
        })
      );
    });
  });
});
