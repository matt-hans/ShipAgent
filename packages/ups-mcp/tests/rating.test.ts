/**
 * Tests for Rating Tools
 *
 * Verifies rating_quote and rating_shop tool behavior.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { registerRatingTools } from "../src/tools/rating.js";
import type { UpsApiClient } from "../src/client/api.js";

// Mock API client
const mockApiClient = {
  post: vi.fn(),
  get: vi.fn(),
  request: vi.fn(),
  delete: vi.fn(),
} as unknown as UpsApiClient;

// Track registered tools
let registeredTools: Map<string, Function> = new Map();

// Mock McpServer
const mockServer = {
  tool: vi.fn((name: string, _schema: unknown, handler: Function) => {
    registeredTools.set(name, handler);
    return { name };
  }),
} as unknown as McpServer;

describe("Rating Tools", () => {
  const accountNumber = "123456";

  beforeEach(() => {
    vi.clearAllMocks();
    registeredTools = new Map();
    registerRatingTools(mockServer, mockApiClient, accountNumber);
  });

  describe("Tool Registration", () => {
    it("should register rating_quote tool", () => {
      expect(mockServer.tool).toHaveBeenCalledWith(
        "rating_quote",
        expect.any(Object),
        expect.any(Function)
      );
    });

    it("should register rating_shop tool", () => {
      expect(mockServer.tool).toHaveBeenCalledWith(
        "rating_shop",
        expect.any(Object),
        expect.any(Function)
      );
    });
  });

  describe("rating_quote", () => {
    const validInput = {
      shipFrom: {
        name: "Sender",
        addressLine1: "123 Main St",
        city: "Atlanta",
        stateProvinceCode: "GA",
        postalCode: "30303",
        countryCode: "US",
      },
      shipTo: {
        name: "Recipient",
        addressLine1: "456 Oak Ave",
        city: "Los Angeles",
        stateProvinceCode: "CA",
        postalCode: "90001",
        countryCode: "US",
      },
      packages: [{ weight: 5 }],
      serviceCode: "03",
    };

    it("should build correct UPS request structure", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "03" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
            TransportationCharges: { CurrencyCode: "USD", MonetaryValue: "10.00" },
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_quote")!;
      await handler(validInput);

      expect(mockApiClient.post).toHaveBeenCalledWith(
        "/rating/v2403/Rate",
        expect.objectContaining({
          RateRequest: expect.objectContaining({
            Shipment: expect.objectContaining({
              Shipper: expect.objectContaining({
                ShipperNumber: accountNumber,
              }),
              Service: { Code: "03" },
            }),
          }),
        })
      );
    });

    it("should transform response with cost breakdown", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "03" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
            TransportationCharges: { CurrencyCode: "USD", MonetaryValue: "10.00" },
            BaseServiceCharge: { CurrencyCode: "USD", MonetaryValue: "8.00" },
            TimeInTransit: {
              ServiceSummary: {
                EstimatedArrival: {
                  Arrival: { Date: "20250128", Time: "235959" },
                  BusinessDaysInTransit: "3",
                },
              },
            },
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_quote")!;
      const result = await handler(validInput);

      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.service.code).toBe("03");
      expect(parsed.service.name).toBe("UPS Ground");
      expect(parsed.available).toBe(true);
      expect(parsed.totalCharges.amount).toBe("12.50");
      expect(parsed.totalCharges.currency).toBe("USD");
      expect(parsed.breakdown).toContainEqual({
        type: "Transportation",
        currency: "USD",
        amount: "10.00",
      });
      expect(parsed.deliveryDate).toBe("20250128");
      expect(parsed.businessDays).toBe(3);
    });

    it("should include fuel surcharge in breakdown", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "03" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "15.00" },
            TransportationCharges: { CurrencyCode: "USD", MonetaryValue: "10.00" },
            RatedPackage: {
              ItemizedCharges: [
                { Code: "376", CurrencyCode: "USD", MonetaryValue: "2.50" },
              ],
            },
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_quote")!;
      const result = await handler(validInput);

      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.breakdown).toContainEqual({
        type: "Fuel Surcharge",
        currency: "USD",
        amount: "2.50",
      });
    });

    it("should require serviceCode", async () => {
      const inputWithoutService = { ...validInput };
      delete (inputWithoutService as Record<string, unknown>).serviceCode;

      const handler = registeredTools.get("rating_quote")!;
      const result = await handler(inputWithoutService);

      expect(result.isError).toBe(true);
    });

    it("should handle API errors", async () => {
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error("UPS API Error [120100]: Invalid address")
      );

      const handler = registeredTools.get("rating_quote")!;
      const result = await handler(validInput);

      expect(result.isError).toBe(true);
      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.error).toBe("UPS API error");
      expect(parsed.message).toContain("Invalid address");
    });
  });

  describe("rating_shop", () => {
    const validInput = {
      shipFrom: {
        name: "Sender",
        addressLine1: "123 Main St",
        city: "Atlanta",
        stateProvinceCode: "GA",
        postalCode: "30303",
        countryCode: "US",
      },
      shipTo: {
        name: "Recipient",
        addressLine1: "456 Oak Ave",
        city: "Los Angeles",
        stateProvinceCode: "CA",
        postalCode: "90001",
        countryCode: "US",
      },
      packages: [{ weight: 5 }],
    };

    it("should return multiple services", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: [
            {
              Service: { Code: "03" },
              TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
            },
            {
              Service: { Code: "02" },
              TotalCharges: { CurrencyCode: "USD", MonetaryValue: "25.00" },
            },
            {
              Service: { Code: "01" },
              TotalCharges: { CurrencyCode: "USD", MonetaryValue: "45.00" },
            },
          ],
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_shop")!;
      const result = await handler(validInput);

      const parsed = JSON.parse(result.content[0].text);
      expect(Array.isArray(parsed)).toBe(true);
      expect(parsed.length).toBe(3);
      expect(parsed[0].service.code).toBe("03"); // Cheapest first
      expect(parsed[1].service.code).toBe("02");
      expect(parsed[2].service.code).toBe("01"); // Most expensive last
    });

    it("should mark unavailable services correctly", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: [
            {
              Service: { Code: "03" },
              TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
            },
            {
              Service: { Code: "01" },
              TotalCharges: { CurrencyCode: "USD", MonetaryValue: "45.00" },
              RatedShipmentAlert: [
                {
                  Code: "110971",
                  Description: "Next Day Air service is not available for this route",
                },
              ],
            },
          ],
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_shop")!;
      const result = await handler(validInput);

      const parsed = JSON.parse(result.content[0].text);

      // Available service should come first
      const groundService = parsed.find((r: { service: { code: string } }) => r.service.code === "03");
      expect(groundService.available).toBe(true);

      // Unavailable service should have reason
      const nextDayService = parsed.find((r: { service: { code: string } }) => r.service.code === "01");
      expect(nextDayService.available).toBe(false);
      expect(nextDayService.unavailableReason).toContain("not available");
    });

    it("should handle missing optional fields gracefully", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "03" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
            // No TransportationCharges, no TimeInTransit, no RatedPackage
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_shop")!;
      const result = await handler(validInput);

      expect(result.isError).toBeUndefined();
      const parsed = JSON.parse(result.content[0].text);
      expect(parsed[0].service.code).toBe("03");
      expect(parsed[0].totalCharges.amount).toBe("12.50");
      // Optional fields should be undefined, not cause errors
      expect(parsed[0].deliveryDate).toBeUndefined();
      expect(parsed[0].breakdown).toBeUndefined();
    });

    it("should call Shop endpoint without service code", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "03" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_shop")!;
      await handler(validInput);

      expect(mockApiClient.post).toHaveBeenCalledWith(
        "/rating/v2403/Shop",
        expect.objectContaining({
          RateRequest: expect.objectContaining({
            Shipment: expect.not.objectContaining({
              Service: expect.anything(),
            }),
          }),
        })
      );
    });
  });

  describe("Service Name Mapping", () => {
    it("should map known service codes to names", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: [
            { Service: { Code: "01" }, TotalCharges: { CurrencyCode: "USD", MonetaryValue: "45.00" } },
            { Service: { Code: "02" }, TotalCharges: { CurrencyCode: "USD", MonetaryValue: "25.00" } },
            { Service: { Code: "03" }, TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" } },
            { Service: { Code: "12" }, TotalCharges: { CurrencyCode: "USD", MonetaryValue: "18.00" } },
            { Service: { Code: "13" }, TotalCharges: { CurrencyCode: "USD", MonetaryValue: "42.00" } },
          ],
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_shop")!;
      const result = await handler({
        shipFrom: {
          name: "Sender",
          addressLine1: "123 Main St",
          city: "Atlanta",
          stateProvinceCode: "GA",
          postalCode: "30303",
        },
        shipTo: {
          name: "Recipient",
          addressLine1: "456 Oak Ave",
          city: "Los Angeles",
          stateProvinceCode: "CA",
          postalCode: "90001",
        },
        packages: [{ weight: 5 }],
      });

      const parsed = JSON.parse(result.content[0].text);
      const serviceNames = parsed.map((r: { service: { name: string } }) => r.service.name);

      expect(serviceNames).toContain("UPS Next Day Air");
      expect(serviceNames).toContain("UPS 2nd Day Air");
      expect(serviceNames).toContain("UPS Ground");
      expect(serviceNames).toContain("UPS 3 Day Select");
      expect(serviceNames).toContain("UPS Next Day Air Saver");
    });

    it("should handle unknown service codes", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "99" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_shop")!;
      const result = await handler({
        shipFrom: {
          name: "Sender",
          addressLine1: "123 Main St",
          city: "Atlanta",
          stateProvinceCode: "GA",
          postalCode: "30303",
        },
        shipTo: {
          name: "Recipient",
          addressLine1: "456 Oak Ave",
          city: "Los Angeles",
          stateProvinceCode: "CA",
          postalCode: "90001",
        },
        packages: [{ weight: 5 }],
      });

      const parsed = JSON.parse(result.content[0].text);
      expect(parsed[0].service.name).toBe("UPS Service 99");
    });
  });

  describe("Package Handling", () => {
    it("should include dimensions when provided", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "03" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "12.50" },
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_quote")!;
      await handler({
        shipFrom: {
          name: "Sender",
          addressLine1: "123 Main St",
          city: "Atlanta",
          stateProvinceCode: "GA",
          postalCode: "30303",
        },
        shipTo: {
          name: "Recipient",
          addressLine1: "456 Oak Ave",
          city: "Los Angeles",
          stateProvinceCode: "CA",
          postalCode: "90001",
        },
        packages: [{ weight: 5, length: 12, width: 8, height: 6 }],
        serviceCode: "03",
      });

      expect(mockApiClient.post).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          RateRequest: expect.objectContaining({
            Shipment: expect.objectContaining({
              Package: expect.objectContaining({
                Dimensions: {
                  UnitOfMeasurement: { Code: "IN" },
                  Length: "12",
                  Width: "8",
                  Height: "6",
                },
              }),
            }),
          }),
        })
      );
    });

    it("should handle multiple packages", async () => {
      const mockResponse = {
        RateResponse: {
          Response: { ResponseStatus: { Code: "1", Description: "Success" } },
          RatedShipment: {
            Service: { Code: "03" },
            TotalCharges: { CurrencyCode: "USD", MonetaryValue: "25.00" },
          },
        },
      };
      (mockApiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const handler = registeredTools.get("rating_quote")!;
      await handler({
        shipFrom: {
          name: "Sender",
          addressLine1: "123 Main St",
          city: "Atlanta",
          stateProvinceCode: "GA",
          postalCode: "30303",
        },
        shipTo: {
          name: "Recipient",
          addressLine1: "456 Oak Ave",
          city: "Los Angeles",
          stateProvinceCode: "CA",
          postalCode: "90001",
        },
        packages: [{ weight: 5 }, { weight: 10 }],
        serviceCode: "03",
      });

      expect(mockApiClient.post).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          RateRequest: expect.objectContaining({
            Shipment: expect.objectContaining({
              Package: expect.arrayContaining([
                expect.objectContaining({
                  PackageWeight: { UnitOfMeasurement: { Code: "LBS" }, Weight: "5" },
                }),
                expect.objectContaining({
                  PackageWeight: { UnitOfMeasurement: { Code: "LBS" }, Weight: "10" },
                }),
              ]),
            }),
          }),
        })
      );
    });
  });
});
