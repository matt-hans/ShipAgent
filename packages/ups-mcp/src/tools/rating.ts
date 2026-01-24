/**
 * UPS Rating MCP Tools
 *
 * Provides MCP tools for UPS rating operations:
 * - rating_quote: Get rate for a specific UPS service
 * - rating_shop: Compare rates across all available services
 *
 * Per CONTEXT.md:
 * - Unavailable services returned with available=false and reason (not omitted)
 * - Error codes passed through as-is from UPS
 */

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { UpsApiClient } from "../client/api.js";
import type { RateResponseWrapper, RatedShipment } from "../generated/rating.js";

// ============================================================================
// Service Name Mapping
// ============================================================================

/**
 * UPS service code to human-readable name mapping
 */
const SERVICE_NAMES: Record<string, string> = {
  "01": "UPS Next Day Air",
  "02": "UPS 2nd Day Air",
  "03": "UPS Ground",
  "07": "UPS Express",
  "08": "UPS Expedited",
  "11": "UPS Standard",
  "12": "UPS 3 Day Select",
  "13": "UPS Next Day Air Saver",
  "14": "UPS Next Day Air Early",
  "17": "UPS Worldwide Economy DDU",
  "54": "UPS Worldwide Express",
  "59": "UPS 2nd Day Air A.M.",
  "65": "UPS Saver",
  "81": "UPS Today Standard",
  "82": "UPS Worldwide Express Plus",
  "83": "UPS Today Dedicated Courier",
  "84": "UPS Today Intercity",
  "85": "UPS Today Express",
  "86": "UPS Today Express Saver",
  "96": "UPS Worldwide Express Freight",
};

/**
 * Gets human-readable service name from code
 *
 * @param code - UPS service code (e.g., "03")
 * @returns Service name (e.g., "UPS Ground")
 */
function getServiceName(code: string): string {
  return SERVICE_NAMES[code] || `UPS Service ${code}`;
}

// ============================================================================
// Input Schema
// ============================================================================

/**
 * Address input schema for rating requests
 */
const AddressInputSchema = z.object({
  name: z.string().describe("Recipient or sender name"),
  addressLine1: z.string().describe("Street address line 1"),
  addressLine2: z.string().optional().describe("Street address line 2"),
  city: z.string().describe("City name"),
  stateProvinceCode: z.string().describe("2-letter state or province code"),
  postalCode: z.string().describe("Postal/ZIP code"),
  countryCode: z.string().default("US").describe("2-letter country code"),
});

/**
 * Package input schema for rating requests
 */
const PackageInputSchema = z.object({
  weight: z.number().describe("Weight in pounds"),
  length: z.number().optional().describe("Length in inches"),
  width: z.number().optional().describe("Width in inches"),
  height: z.number().optional().describe("Height in inches"),
  packagingType: z
    .string()
    .default("02")
    .describe("UPS packaging type code: 02=Package, 01=Letter, 00=Unknown"),
});

/**
 * Rate request input schema
 */
const RateRequestInputSchema = z.object({
  shipFrom: AddressInputSchema.describe("Origin address"),
  shipTo: AddressInputSchema.describe("Destination address"),
  packages: z
    .array(PackageInputSchema)
    .min(1)
    .describe("Array of packages to ship"),
  serviceCode: z
    .string()
    .optional()
    .describe('UPS service code (e.g., "03" for Ground). Required for rating_quote'),
});

type RateRequestInput = z.infer<typeof RateRequestInputSchema>;

// ============================================================================
// Output Schema
// ============================================================================

/**
 * Cost breakdown item
 */
const CostBreakdownSchema = z.object({
  type: z.string().describe("Charge type (Transportation, Fuel Surcharge, etc.)"),
  currency: z.string().describe("Currency code (USD, etc.)"),
  amount: z.string().describe("Monetary amount as string"),
});

/**
 * Rate response output schema
 */
const RateResponseOutputSchema = z.object({
  service: z.object({
    code: z.string().describe("UPS service code"),
    name: z.string().describe("Human-readable service name"),
  }),
  available: z.boolean().describe("Whether this service is available for this shipment"),
  unavailableReason: z
    .string()
    .optional()
    .describe("Reason service is unavailable (if available=false)"),
  totalCharges: z
    .object({
      currency: z.string(),
      amount: z.string(),
    })
    .optional()
    .describe("Total charges for this service"),
  breakdown: z
    .array(CostBreakdownSchema)
    .optional()
    .describe("Itemized cost breakdown"),
  deliveryDate: z.string().optional().describe("Estimated delivery date (YYYYMMDD)"),
  deliveryTime: z.string().optional().describe("Estimated delivery time (HHMMSS)"),
  businessDays: z.number().optional().describe("Business days in transit"),
});

type RateResponseOutput = z.infer<typeof RateResponseOutputSchema>;

// ============================================================================
// Response Transformation
// ============================================================================

/**
 * Transforms UPS rated shipment to our output format
 *
 * @param rated - UPS RatedShipment object
 * @returns Structured rate response
 */
function transformRatedShipment(rated: RatedShipment): RateResponseOutput {
  const service = rated.Service;
  const charges = rated.TotalCharges;
  const breakdown: Array<{ type: string; currency: string; amount: string }> = [];

  // Base transportation charge
  if (rated.TransportationCharges) {
    breakdown.push({
      type: "Transportation",
      currency: rated.TransportationCharges.CurrencyCode,
      amount: rated.TransportationCharges.MonetaryValue,
    });
  }

  // Base service charge
  if (rated.BaseServiceCharge) {
    breakdown.push({
      type: "Base Service",
      currency: rated.BaseServiceCharge.CurrencyCode,
      amount: rated.BaseServiceCharge.MonetaryValue,
    });
  }

  // Service options charges
  if (rated.ServiceOptionsCharges) {
    breakdown.push({
      type: "Service Options",
      currency: rated.ServiceOptionsCharges.CurrencyCode,
      amount: rated.ServiceOptionsCharges.MonetaryValue,
    });
  }

  // Check for alerts that might indicate issues
  let unavailableReason: string | undefined;
  if (rated.RatedShipmentAlert && rated.RatedShipmentAlert.length > 0) {
    // Check for service unavailability alerts
    const unavailableAlert = rated.RatedShipmentAlert.find(
      (alert) =>
        alert.Code === "110971" || // Service not available
        alert.Code === "110920" || // No services available
        alert.Description?.toLowerCase().includes("not available")
    );
    if (unavailableAlert) {
      unavailableReason = unavailableAlert.Description;
    }
  }

  // Time in transit information
  const transit = rated.TimeInTransit;
  const estimatedArrival = transit?.ServiceSummary?.EstimatedArrival;

  // Guaranteed delivery info (fallback)
  const guaranteed = rated.GuaranteedDelivery;

  return {
    service: {
      code: service.Code,
      name: getServiceName(service.Code),
    },
    available: !unavailableReason,
    unavailableReason,
    totalCharges: charges
      ? {
          currency: charges.CurrencyCode,
          amount: charges.MonetaryValue,
        }
      : undefined,
    breakdown: breakdown.length > 0 ? breakdown : undefined,
    deliveryDate: estimatedArrival?.Arrival?.Date,
    deliveryTime:
      estimatedArrival?.Arrival?.Time || guaranteed?.DeliveryByTime,
    businessDays: estimatedArrival?.BusinessDaysInTransit
      ? parseInt(estimatedArrival.BusinessDaysInTransit, 10)
      : guaranteed?.BusinessDaysInTransit
        ? parseInt(guaranteed.BusinessDaysInTransit, 10)
        : undefined,
  };
}

/**
 * Transforms full UPS rate response to array of rate outputs
 *
 * @param upsResponse - Raw UPS API response
 * @returns Array of structured rate responses
 */
function transformRateResponse(upsResponse: RateResponseWrapper): RateResponseOutput[] {
  const ratedShipment = upsResponse.RateResponse?.RatedShipment;

  if (!ratedShipment) {
    return [];
  }

  // Handle single shipment or array
  const shipments = Array.isArray(ratedShipment) ? ratedShipment : [ratedShipment];

  return shipments.map(transformRatedShipment);
}

// ============================================================================
// Request Building
// ============================================================================

/**
 * Builds UPS API rate request from input
 *
 * @param input - Validated rate request input
 * @param serviceCode - Optional service code for specific rate
 * @param accountNumber - UPS shipper account number
 * @returns UPS API request body
 */
function buildRateRequest(
  input: RateRequestInput,
  serviceCode: string | undefined,
  accountNumber: string
): object {
  // Build packages array
  const packages = input.packages.map((pkg) => {
    const pkgObj: Record<string, unknown> = {
      PackagingType: {
        Code: pkg.packagingType,
      },
      PackageWeight: {
        UnitOfMeasurement: {
          Code: "LBS",
        },
        Weight: pkg.weight.toString(),
      },
    };

    // Add dimensions if provided
    if (pkg.length !== undefined && pkg.width !== undefined && pkg.height !== undefined) {
      pkgObj.Dimensions = {
        UnitOfMeasurement: {
          Code: "IN",
        },
        Length: pkg.length.toString(),
        Width: pkg.width.toString(),
        Height: pkg.height.toString(),
      };
    }

    return pkgObj;
  });

  // Build request
  const request: Record<string, unknown> = {
    RateRequest: {
      Request: {
        SubVersion: "2403",
      },
      Shipment: {
        Shipper: {
          Name: input.shipFrom.name,
          ShipperNumber: accountNumber,
          Address: {
            AddressLine: [input.shipFrom.addressLine1, input.shipFrom.addressLine2].filter(
              Boolean
            ),
            City: input.shipFrom.city,
            StateProvinceCode: input.shipFrom.stateProvinceCode,
            PostalCode: input.shipFrom.postalCode,
            CountryCode: input.shipFrom.countryCode,
          },
        },
        ShipTo: {
          Name: input.shipTo.name,
          Address: {
            AddressLine: [input.shipTo.addressLine1, input.shipTo.addressLine2].filter(Boolean),
            City: input.shipTo.city,
            StateProvinceCode: input.shipTo.stateProvinceCode,
            PostalCode: input.shipTo.postalCode,
            CountryCode: input.shipTo.countryCode,
          },
        },
        ShipFrom: {
          Name: input.shipFrom.name,
          Address: {
            AddressLine: [input.shipFrom.addressLine1, input.shipFrom.addressLine2].filter(
              Boolean
            ),
            City: input.shipFrom.city,
            StateProvinceCode: input.shipFrom.stateProvinceCode,
            PostalCode: input.shipFrom.postalCode,
            CountryCode: input.shipFrom.countryCode,
          },
        },
        Package: packages.length === 1 ? packages[0] : packages,
        PaymentDetails: {
          ShipmentCharge: {
            Type: "01", // Transportation
            BillShipper: {
              AccountNumber: accountNumber,
            },
          },
        },
      },
    },
  };

  // Add service if specified (for rate quote)
  if (serviceCode) {
    (request.RateRequest as Record<string, unknown>).Shipment = {
      ...(request.RateRequest as Record<string, Record<string, unknown>>).Shipment,
      Service: {
        Code: serviceCode,
      },
    };
  }

  return request;
}

// ============================================================================
// Tool Input Schemas (for MCP registration)
// ============================================================================

/**
 * Zod schema for rating_quote tool input
 */
const RatingQuoteInputSchema = z.object({
  shipFrom: AddressInputSchema.describe("Origin address"),
  shipTo: AddressInputSchema.describe("Destination address"),
  packages: z
    .array(PackageInputSchema)
    .min(1)
    .describe("Array of packages to ship"),
  serviceCode: z
    .string()
    .describe('UPS service code (required): "01"=Next Day Air, "02"=2nd Day Air, "03"=Ground, "12"=3 Day Select, "13"=Next Day Air Saver'),
});

/**
 * Zod schema for rating_shop tool input
 */
const RatingShopInputSchema = z.object({
  shipFrom: AddressInputSchema.describe("Origin address"),
  shipTo: AddressInputSchema.describe("Destination address"),
  packages: z
    .array(PackageInputSchema)
    .min(1)
    .describe("Array of packages to ship"),
});

// ============================================================================
// Tool Registration
// ============================================================================

/**
 * Registers rating MCP tools with the server
 *
 * @param server - MCP server instance
 * @param apiClient - UPS API client for making requests
 * @param accountNumber - UPS shipper account number
 */
export function registerRatingTools(
  server: McpServer,
  apiClient: UpsApiClient,
  accountNumber: string
): void {
  /**
   * rating_quote - Get rate for a specific UPS service
   */
  server.tool(
    "rating_quote",
    RatingQuoteInputSchema.shape,
    async (args) => {
      // Validate input
      const parsed = RatingQuoteInputSchema.safeParse(args);
      if (!parsed.success) {
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify({ error: "Invalid input", details: parsed.error.format() }),
            },
          ],
          isError: true,
        };
      }

      const input = parsed.data;

      try {
        // Build and send request
        const requestBody = buildRateRequest(input, input.serviceCode, accountNumber);
        const response = await apiClient.post<RateResponseWrapper>(
          "/rating/v2403/Rate",
          requestBody
        );

        // Transform response
        const rates = transformRateResponse(response);

        if (rates.length === 0) {
          return {
            content: [
              {
                type: "text" as const,
                text: JSON.stringify({
                  error: "No rates returned",
                  message: "UPS did not return any rates for this shipment",
                }),
              },
            ],
            isError: true,
          };
        }

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(rates[0], null, 2),
            },
          ],
        };
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify({ error: "UPS API error", message: errorMessage }),
            },
          ],
          isError: true,
        };
      }
    }
  );

  /**
   * rating_shop - Compare rates across all available UPS services
   */
  server.tool(
    "rating_shop",
    RatingShopInputSchema.shape,
    async (args) => {
      // Validate input
      const parsed = RatingShopInputSchema.safeParse(args);
      if (!parsed.success) {
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify({ error: "Invalid input", details: parsed.error.format() }),
            },
          ],
          isError: true,
        };
      }

      const input = parsed.data;

      try {
        // Build request without service code to get all available services
        const requestBody = buildRateRequest(input, undefined, accountNumber);
        const response = await apiClient.post<RateResponseWrapper>(
          "/rating/v2403/Shop",
          requestBody
        );

        // Transform response
        const rates = transformRateResponse(response);

        // Sort by price (available services first, then by amount)
        rates.sort((a, b) => {
          // Available services come first
          if (a.available !== b.available) {
            return a.available ? -1 : 1;
          }
          // Then sort by price
          const priceA = parseFloat(a.totalCharges?.amount || "999999");
          const priceB = parseFloat(b.totalCharges?.amount || "999999");
          return priceA - priceB;
        });

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(rates, null, 2),
            },
          ],
        };
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify({ error: "UPS API error", message: errorMessage }),
            },
          ],
          isError: true,
        };
      }
    }
  );
}
