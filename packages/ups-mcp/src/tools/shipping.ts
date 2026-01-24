/**
 * Shipping Tools Module
 *
 * Implements MCP tools for UPS shipment management:
 * - shipping_create: Create shipment with PDF label
 * - shipping_void: Void/cancel existing shipment
 * - shipping_get_label: Retrieve and save label for existing tracking number
 */

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { UpsApiClient } from "../client/api.js";
import { saveLabel, extractLabelFromResponse } from "../utils/labels.js";
import type { ShipResponseWrapper } from "../generated/shipping.js";

// ============================================================================
// Input Schemas
// ============================================================================

/**
 * Address input schema for shipper/shipTo
 */
const AddressInputSchema = z.object({
  name: z.string().describe("Company or recipient name"),
  attentionName: z.string().optional().describe("Attention name"),
  phone: z.string().describe("Phone number"),
  addressLine1: z.string().describe("Street address line 1"),
  addressLine2: z.string().optional().describe("Street address line 2"),
  city: z.string().describe("City name"),
  stateProvinceCode: z.string().describe("State/province code (e.g., CA, NY)"),
  postalCode: z.string().describe("Postal/ZIP code"),
  countryCode: z.string().default("US").describe("Country code (default: US)"),
});

/**
 * Package input schema
 */
const PackageInputSchema = z.object({
  weight: z.number().describe("Weight in pounds"),
  length: z.number().optional().describe("Length in inches"),
  width: z.number().optional().describe("Width in inches"),
  height: z.number().optional().describe("Height in inches"),
  packagingType: z
    .string()
    .default("02")
    .describe('UPS packaging type code (default: "02" Customer Supplied Package)'),
  description: z.string().optional().describe("Package description"),
});

/**
 * Shipment creation request schema
 */
const ShipmentRequestInputSchema = z.object({
  shipper: AddressInputSchema.describe("Shipper (sender) information"),
  shipTo: AddressInputSchema.describe("Ship-to (recipient) information"),
  packages: z.array(PackageInputSchema).describe("Array of packages"),
  serviceCode: z
    .string()
    .describe('UPS service code (e.g., "03" for Ground, "01" for Next Day Air)'),
  description: z.string().optional().describe("Shipment description"),
  reference: z.string().optional().describe("Customer reference number"),
});

/**
 * Void shipment request schema
 */
const VoidRequestSchema = z.object({
  trackingNumber: z.string().describe("UPS tracking number to void"),
});

/**
 * Get label request schema
 */
const GetLabelRequestSchema = z.object({
  trackingNumber: z
    .string()
    .describe("UPS tracking number to get label for"),
});

// ============================================================================
// Response Types
// ============================================================================

/**
 * Result of shipping_create tool
 */
interface ShipmentCreateResult {
  success: boolean;
  trackingNumbers: string[];
  labelPaths: string[];
  totalCharges: {
    currencyCode: string;
    monetaryValue: string;
  };
  shipmentIdentificationNumber: string;
}

/**
 * Result of shipping_void tool
 */
interface ShipmentVoidResult {
  success: boolean;
  trackingNumber: string;
  status: {
    code: string;
    description: string;
  };
}

/**
 * Result of shipping_get_label tool
 */
interface GetLabelResult {
  success: boolean;
  trackingNumber: string;
  labelPath: string;
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Transform simplified input to UPS API request format
 */
function buildShipmentRequest(
  input: z.infer<typeof ShipmentRequestInputSchema>,
  accountNumber: string
): unknown {
  // Build packages array
  const packages = input.packages.map((pkg) => {
    const packageObj: Record<string, unknown> = {
      Packaging: {
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
    if (pkg.length && pkg.width && pkg.height) {
      packageObj.Dimensions = {
        UnitOfMeasurement: {
          Code: "IN",
        },
        Length: pkg.length.toString(),
        Width: pkg.width.toString(),
        Height: pkg.height.toString(),
      };
    }

    // Add description if provided
    if (pkg.description) {
      packageObj.Description = pkg.description;
    }

    return packageObj;
  });

  // Build address lines array
  const buildAddressLines = (addr: z.infer<typeof AddressInputSchema>) => {
    const lines = [addr.addressLine1];
    if (addr.addressLine2) {
      lines.push(addr.addressLine2);
    }
    return lines;
  };

  return {
    ShipmentRequest: {
      Shipment: {
        Description: input.description || "Shipment",
        Shipper: {
          Name: input.shipper.name,
          AttentionName: input.shipper.attentionName,
          Phone: {
            Number: input.shipper.phone,
          },
          ShipperNumber: accountNumber,
          Address: {
            AddressLine: buildAddressLines(input.shipper),
            City: input.shipper.city,
            StateProvinceCode: input.shipper.stateProvinceCode,
            PostalCode: input.shipper.postalCode,
            CountryCode: input.shipper.countryCode,
          },
        },
        ShipTo: {
          Name: input.shipTo.name,
          AttentionName: input.shipTo.attentionName,
          Phone: {
            Number: input.shipTo.phone,
          },
          Address: {
            AddressLine: buildAddressLines(input.shipTo),
            City: input.shipTo.city,
            StateProvinceCode: input.shipTo.stateProvinceCode,
            PostalCode: input.shipTo.postalCode,
            CountryCode: input.shipTo.countryCode,
          },
        },
        PaymentInformation: {
          ShipmentCharge: {
            Type: "01", // Transportation charges
            BillShipper: {
              AccountNumber: accountNumber,
            },
          },
        },
        Service: {
          Code: input.serviceCode,
        },
        Package: packages.length === 1 ? packages[0] : packages,
      },
      LabelSpecification: {
        LabelImageFormat: {
          Code: "PDF",
        },
      },
    },
  };
}

// ============================================================================
// Tool Registration
// ============================================================================

/**
 * Register shipping tools with the MCP server
 *
 * @param server - MCP server instance
 * @param apiClient - UPS API client
 * @param accountNumber - UPS shipper account number
 * @param labelsOutputDir - Directory to save label files
 */
export function registerShippingTools(
  server: McpServer,
  apiClient: UpsApiClient,
  accountNumber: string,
  labelsOutputDir: string
): void {
  // =========================================================================
  // shipping_create
  // =========================================================================
  server.tool(
    "shipping_create",
    ShipmentRequestInputSchema.shape,
    { title: "Create a UPS shipment and get PDF label" },
    async (args): Promise<{ content: Array<{ type: "text"; text: string }> }> => {
      // Parse and validate input
      const input = ShipmentRequestInputSchema.parse(args);

      // Build UPS request
      const requestBody = buildShipmentRequest(input, accountNumber);

      // Call UPS Shipping API
      const response = await apiClient.post<ShipResponseWrapper>(
        "/shipments/v2409/ship",
        requestBody
      );

      // Extract labels
      const labels = extractLabelFromResponse(response);

      // Save labels to filesystem
      const labelPaths: string[] = [];
      for (const label of labels) {
        const path = await saveLabel(
          label.trackingNumber,
          label.base64Data,
          labelsOutputDir
        );
        labelPaths.push(path);
      }

      // Extract tracking numbers
      const trackingNumbers = labels.map((l) => l.trackingNumber);

      // Extract charges
      const charges = response.ShipmentResponse.ShipmentResults.ShipmentCharges;
      const totalCharges = charges?.TotalCharges || {
        CurrencyCode: "USD",
        MonetaryValue: "0.00",
      };

      const result: ShipmentCreateResult = {
        success: true,
        trackingNumbers,
        labelPaths,
        totalCharges: {
          currencyCode: totalCharges.CurrencyCode,
          monetaryValue: totalCharges.MonetaryValue,
        },
        shipmentIdentificationNumber:
          response.ShipmentResponse.ShipmentResults.ShipmentIdentificationNumber,
      };

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }
  );

  // =========================================================================
  // shipping_void
  // =========================================================================
  server.tool(
    "shipping_void",
    VoidRequestSchema.shape,
    { title: "Void/cancel an existing UPS shipment" },
    async (args): Promise<{ content: Array<{ type: "text"; text: string }> }> => {
      // Parse and validate input
      const input = VoidRequestSchema.parse(args);

      // Call UPS Void API
      // DELETE /shipments/v2409/void/cancel/{trackingNumber}
      const response = await apiClient.delete<{
        VoidShipmentResponse: {
          Response: { ResponseStatus: { Code: string; Description: string } };
          SummaryResult: {
            Status: { Code: string; Description: string };
          };
        };
      }>(`/shipments/v2409/void/cancel/${input.trackingNumber}`);

      const status = response.VoidShipmentResponse.SummaryResult.Status;

      const result: ShipmentVoidResult = {
        success: status.Code === "1", // Code "1" means successfully voided
        trackingNumber: input.trackingNumber,
        status: {
          code: status.Code,
          description: status.Description,
        },
      };

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }
  );

  // =========================================================================
  // shipping_get_label
  // =========================================================================
  server.tool(
    "shipping_get_label",
    GetLabelRequestSchema.shape,
    { title: "Retrieve and save label for existing tracking number" },
    async (args): Promise<{ content: Array<{ type: "text"; text: string }> }> => {
      // Parse and validate input
      const input = GetLabelRequestSchema.parse(args);

      // Call UPS Label Recovery API
      // POST /labels/v2409/recovery with tracking number in body
      const response = await apiClient.post<{
        LabelRecoveryResponse: {
          LabelResults: {
            TrackingNumber: string;
            LabelImage: {
              LabelImageFormat: { Code: string };
              GraphicImage: string;
            };
          };
        };
      }>("/labels/v2409/recovery", {
        LabelRecoveryRequest: {
          LabelSpecification: {
            LabelImageFormat: {
              Code: "PDF",
            },
          },
          TrackingNumber: input.trackingNumber,
        },
      });

      const labelResults = response.LabelRecoveryResponse.LabelResults;
      const base64Data = labelResults.LabelImage.GraphicImage;

      // Save label (overwrites existing if present per CONTEXT.md)
      const labelPath = await saveLabel(
        input.trackingNumber,
        base64Data,
        labelsOutputDir
      );

      const result: GetLabelResult = {
        success: true,
        trackingNumber: input.trackingNumber,
        labelPath,
      };

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }
  );
}
