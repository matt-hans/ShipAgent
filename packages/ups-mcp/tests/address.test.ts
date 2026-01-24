/**
 * Tests for Address Validation Tool
 *
 * Verifies address_validate tool behavior for valid, ambiguous, and invalid addresses.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { registerAddressTools } from "../src/tools/address.js";
import type { UpsApiClient } from "../src/client/api.js";

describe("address_validate tool", () => {
  let mockApiClient: { post: ReturnType<typeof vi.fn> };
  let registeredTool: {
    name: string;
    handler: (params: Record<string, unknown>) => Promise<{
      content: Array<{ type: string; text: string }>;
      structuredContent: Record<string, unknown>;
    }>;
  } | null = null;

  beforeEach(() => {
    vi.clearAllMocks();

    // Create mock API client
    mockApiClient = {
      post: vi.fn(),
    };

    // Create a mock server that captures the registered tool
    const mockServer = {
      tool: vi.fn((name, _description, _inputSchema, handler) => {
        registeredTool = { name, handler };
      }),
    } as unknown as McpServer;

    // Register the tools
    registerAddressTools(mockServer, mockApiClient as unknown as UpsApiClient);
  });

  /**
   * Helper to call the registered tool
   */
  async function callAddressValidate(input: Record<string, unknown>) {
    if (!registeredTool) {
      throw new Error("Tool not registered");
    }
    return registeredTool.handler(input);
  }

  describe("valid address", () => {
    it("should return status 'valid' with standardized address", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressClassification: { Code: "2", Description: "Residential" },
              AddressLine: ["123 MAIN ST"],
              PoliticalDivision2: "LOS ANGELES",
              PoliticalDivision1: "CA",
              PostcodePrimaryLow: "90001",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "123 Main St",
        city: "Los Angeles",
        stateProvinceCode: "CA",
        postalCode: "90001",
        countryCode: "US",
      });

      expect(result.structuredContent.status).toBe("valid");
      expect(result.structuredContent.validatedAddress).toEqual({
        addressLine1: "123 MAIN ST",
        addressLine2: undefined,
        city: "LOS ANGELES",
        stateProvinceCode: "CA",
        postalCode: "90001",
        countryCode: "US",
      });
    });

    it("should include classification for valid address", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressClassification: { Code: "2", Description: "Residential" },
              AddressLine: ["123 MAIN ST"],
              PoliticalDivision2: "LOS ANGELES",
              PoliticalDivision1: "CA",
              PostcodePrimaryLow: "90001",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "123 Main St",
        city: "Los Angeles",
        stateProvinceCode: "CA",
        postalCode: "90001",
        countryCode: "US",
      });

      expect(result.structuredContent.classification).toBe("residential");
    });

    it("should handle commercial classification", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressClassification: { Code: "1", Description: "Commercial" },
              AddressLine: ["456 BUSINESS BLVD"],
              PoliticalDivision2: "SAN FRANCISCO",
              PoliticalDivision1: "CA",
              PostcodePrimaryLow: "94102",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "456 Business Blvd",
        city: "San Francisco",
        stateProvinceCode: "CA",
        postalCode: "94102",
        countryCode: "US",
      });

      expect(result.structuredContent.classification).toBe("commercial");
    });

    it("should format ZIP+4 postal code correctly", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressClassification: { Code: "2" },
              AddressLine: ["789 OAK AVE"],
              PoliticalDivision2: "SEATTLE",
              PoliticalDivision1: "WA",
              PostcodePrimaryLow: "98101",
              PostcodeExtendedLow: "1234",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "789 Oak Ave",
        city: "Seattle",
        stateProvinceCode: "WA",
        postalCode: "98101",
        countryCode: "US",
      });

      expect(result.structuredContent.validatedAddress).toMatchObject({
        postalCode: "98101-1234",
      });
    });
  });

  describe("ambiguous address", () => {
    it("should return status 'ambiguous' with candidates array", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          AmbiguousAddressIndicator: "",
          Candidate: [
            {
              AddressClassification: { Code: "2" },
              AddressLine: ["123 MAIN ST"],
              PoliticalDivision2: "LOS ANGELES",
              PoliticalDivision1: "CA",
              PostcodePrimaryLow: "90001",
              CountryCode: "US",
            },
            {
              AddressClassification: { Code: "1" },
              AddressLine: ["123 MAIN AVE"],
              PoliticalDivision2: "LOS ANGELES",
              PoliticalDivision1: "CA",
              PostcodePrimaryLow: "90002",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "123 Main",
        city: "Los Angeles",
        stateProvinceCode: "CA",
        postalCode: "90001",
        countryCode: "US",
      });

      expect(result.structuredContent.status).toBe("ambiguous");
      expect(result.structuredContent.candidates).toHaveLength(2);
      expect(result.structuredContent.candidates).toEqual([
        {
          addressLine1: "123 MAIN ST",
          addressLine2: undefined,
          city: "LOS ANGELES",
          stateProvinceCode: "CA",
          postalCode: "90001",
          countryCode: "US",
          classification: "residential",
        },
        {
          addressLine1: "123 MAIN AVE",
          addressLine2: undefined,
          city: "LOS ANGELES",
          stateProvinceCode: "CA",
          postalCode: "90002",
          countryCode: "US",
          classification: "commercial",
        },
      ]);
    });

    it("should include classification on each candidate", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          AmbiguousAddressIndicator: "",
          Candidate: [
            {
              AddressClassification: { Code: "1" },
              AddressLine: ["100 FIRST ST"],
              PoliticalDivision2: "DENVER",
              PoliticalDivision1: "CO",
              PostcodePrimaryLow: "80202",
              CountryCode: "US",
            },
            {
              AddressClassification: { Code: "2" },
              AddressLine: ["100 FIRST AVE"],
              PoliticalDivision2: "DENVER",
              PoliticalDivision1: "CO",
              PostcodePrimaryLow: "80203",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "100 First",
        city: "Denver",
        stateProvinceCode: "CO",
        postalCode: "80202",
        countryCode: "US",
      });

      const candidates = result.structuredContent.candidates as Array<{ classification: string }>;
      expect(candidates[0].classification).toBe("commercial");
      expect(candidates[1].classification).toBe("residential");
    });
  });

  describe("invalid address", () => {
    it("should return status 'invalid' with reason when no candidates", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          NoCandidatesIndicator: "",
        },
      });

      const result = await callAddressValidate({
        addressLine1: "99999 Nonexistent Road",
        city: "Nowhere",
        stateProvinceCode: "XX",
        postalCode: "00000",
        countryCode: "US",
      });

      expect(result.structuredContent.status).toBe("invalid");
      expect(result.structuredContent.invalidReason).toBeDefined();
      expect(typeof result.structuredContent.invalidReason).toBe("string");
    });

    it("should provide meaningful error message for invalid address", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          NoCandidatesIndicator: "",
        },
      });

      const result = await callAddressValidate({
        addressLine1: "Invalid Address",
        city: "Fake City",
        stateProvinceCode: "ZZ",
        postalCode: "99999",
        countryCode: "US",
      });

      expect(result.structuredContent.invalidReason).toContain("No valid address");
    });
  });

  describe("optional fields", () => {
    it("should handle missing addressLine2 gracefully", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressLine: ["123 MAIN ST"],
              PoliticalDivision2: "PORTLAND",
              PoliticalDivision1: "OR",
              PostcodePrimaryLow: "97201",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "123 Main St",
        city: "Portland",
        stateProvinceCode: "OR",
        postalCode: "97201",
        countryCode: "US",
      });

      expect(result.structuredContent.status).toBe("valid");
      expect(result.structuredContent.validatedAddress).toMatchObject({
        addressLine1: "123 MAIN ST",
      });
    });

    it("should handle address with addressLine2", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressLine: ["123 MAIN ST", "APT 456"],
              PoliticalDivision2: "CHICAGO",
              PoliticalDivision1: "IL",
              PostcodePrimaryLow: "60601",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "123 Main St",
        addressLine2: "Apt 456",
        city: "Chicago",
        stateProvinceCode: "IL",
        postalCode: "60601",
        countryCode: "US",
      });

      expect(result.structuredContent.validatedAddress).toMatchObject({
        addressLine1: "123 MAIN ST",
        addressLine2: "APT 456",
      });
    });

    it("should default countryCode to US when not provided", async () => {
      mockApiClient.post.mockImplementationOnce((path, body) => {
        // Verify the request includes default country code
        const request = body as { XAVRequest: { AddressKeyFormat: { CountryCode: string } } };
        expect(request.XAVRequest.AddressKeyFormat.CountryCode).toBe("US");

        return Promise.resolve({
          XAVResponse: {
            ValidAddressIndicator: "",
            Candidate: [
              {
                AddressLine: ["123 MAIN ST"],
                PoliticalDivision2: "BOSTON",
                PoliticalDivision1: "MA",
                PostcodePrimaryLow: "02101",
                CountryCode: "US",
              },
            ],
          },
        });
      });

      const result = await callAddressValidate({
        addressLine1: "123 Main St",
        city: "Boston",
        stateProvinceCode: "MA",
        postalCode: "02101",
        // countryCode not provided - should default to US
      });

      expect(result.structuredContent.status).toBe("valid");
    });

    it("should handle unknown classification code", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressClassification: { Code: "0" },
              AddressLine: ["123 UNKNOWN ST"],
              PoliticalDivision2: "MIAMI",
              PoliticalDivision1: "FL",
              PostcodePrimaryLow: "33101",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "123 Unknown St",
        city: "Miami",
        stateProvinceCode: "FL",
        postalCode: "33101",
        countryCode: "US",
      });

      expect(result.structuredContent.classification).toBe("unknown");
    });

    it("should handle missing classification", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              // No AddressClassification
              AddressLine: ["123 TEST ST"],
              PoliticalDivision2: "PHOENIX",
              PoliticalDivision1: "AZ",
              PostcodePrimaryLow: "85001",
              CountryCode: "US",
            },
          ],
        },
      });

      const result = await callAddressValidate({
        addressLine1: "123 Test St",
        city: "Phoenix",
        stateProvinceCode: "AZ",
        postalCode: "85001",
        countryCode: "US",
      });

      expect(result.structuredContent.classification).toBe("unknown");
    });
  });

  describe("API request format", () => {
    it("should call correct API endpoint", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressLine: ["123 TEST ST"],
              PoliticalDivision2: "NEW YORK",
              PoliticalDivision1: "NY",
              PostcodePrimaryLow: "10001",
              CountryCode: "US",
            },
          ],
        },
      });

      await callAddressValidate({
        addressLine1: "123 Test St",
        city: "New York",
        stateProvinceCode: "NY",
        postalCode: "10001",
        countryCode: "US",
      });

      expect(mockApiClient.post).toHaveBeenCalledWith(
        "/addressvalidation/v2/1",
        expect.objectContaining({
          XAVRequest: expect.objectContaining({
            AddressKeyFormat: expect.objectContaining({
              AddressLine: ["123 Test St"],
              PoliticalDivision2: "New York",
              PoliticalDivision1: "NY",
              PostcodePrimaryLow: "10001",
              CountryCode: "US",
            }),
          }),
        })
      );
    });

    it("should include addressLine2 in request when provided", async () => {
      mockApiClient.post.mockResolvedValueOnce({
        XAVResponse: {
          ValidAddressIndicator: "",
          Candidate: [
            {
              AddressLine: ["123 TEST ST", "SUITE 100"],
              PoliticalDivision2: "AUSTIN",
              PoliticalDivision1: "TX",
              PostcodePrimaryLow: "78701",
              CountryCode: "US",
            },
          ],
        },
      });

      await callAddressValidate({
        addressLine1: "123 Test St",
        addressLine2: "Suite 100",
        city: "Austin",
        stateProvinceCode: "TX",
        postalCode: "78701",
        countryCode: "US",
      });

      expect(mockApiClient.post).toHaveBeenCalledWith(
        "/addressvalidation/v2/1",
        expect.objectContaining({
          XAVRequest: expect.objectContaining({
            AddressKeyFormat: expect.objectContaining({
              AddressLine: ["123 Test St", "Suite 100"],
            }),
          }),
        })
      );
    });
  });
});
