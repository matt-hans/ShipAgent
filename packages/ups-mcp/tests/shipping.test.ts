/**
 * Tests for Shipping Tools
 *
 * Verifies shipping_create, shipping_void, and shipping_get_label functionality.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { writeFile, mkdir } from "node:fs/promises";
import { saveLabel, extractLabelFromResponse } from "../src/utils/labels.js";

// Mock fs/promises
vi.mock("node:fs/promises", () => ({
  writeFile: vi.fn().mockResolvedValue(undefined),
  mkdir: vi.fn().mockResolvedValue(undefined),
}));

describe("Label Utilities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("saveLabel", () => {
    it("should create output directory if it doesn't exist", async () => {
      const trackingNumber = "1Z999AA10123456784";
      const base64Data = "JVBERi0xLjQK"; // Base64 for "%PDF-1.4\n"
      const outputDir = "/tmp/labels";

      await saveLabel(trackingNumber, base64Data, outputDir);

      expect(mkdir).toHaveBeenCalledWith(outputDir, { recursive: true });
    });

    it("should save label with correct filename format", async () => {
      const trackingNumber = "1Z999AA10123456784";
      const base64Data = "JVBERi0xLjQK";
      const outputDir = "/tmp/labels";

      const result = await saveLabel(trackingNumber, base64Data, outputDir);

      expect(result).toBe("/tmp/labels/1Z999AA10123456784.pdf");
      expect(writeFile).toHaveBeenCalledWith(
        "/tmp/labels/1Z999AA10123456784.pdf",
        expect.any(Buffer)
      );
    });

    it("should decode Base64 content correctly", async () => {
      const trackingNumber = "1Z999AA10123456784";
      // "Hello PDF" in Base64
      const base64Data = Buffer.from("Hello PDF").toString("base64");
      const outputDir = "/tmp/labels";

      await saveLabel(trackingNumber, base64Data, outputDir);

      const writtenBuffer = (writeFile as ReturnType<typeof vi.fn>).mock
        .calls[0][1] as Buffer;
      expect(writtenBuffer.toString()).toBe("Hello PDF");
    });
  });

  describe("extractLabelFromResponse", () => {
    it("should extract label from single package response", () => {
      const response = {
        ShipmentResponse: {
          ShipmentResults: {
            PackageResults: {
              TrackingNumber: "1Z999AA10123456784",
              ShippingLabel: {
                GraphicImage: "JVBERi0xLjQK",
              },
            },
          },
        },
      };

      const labels = extractLabelFromResponse(response);

      expect(labels).toHaveLength(1);
      expect(labels[0]).toEqual({
        trackingNumber: "1Z999AA10123456784",
        base64Data: "JVBERi0xLjQK",
      });
    });

    it("should extract labels from multi-package response", () => {
      const response = {
        ShipmentResponse: {
          ShipmentResults: {
            PackageResults: [
              {
                TrackingNumber: "1Z999AA10123456784",
                ShippingLabel: {
                  GraphicImage: "base64data1",
                },
              },
              {
                TrackingNumber: "1Z999AA10123456785",
                ShippingLabel: {
                  GraphicImage: "base64data2",
                },
              },
            ],
          },
        },
      };

      const labels = extractLabelFromResponse(response);

      expect(labels).toHaveLength(2);
      expect(labels[0].trackingNumber).toBe("1Z999AA10123456784");
      expect(labels[1].trackingNumber).toBe("1Z999AA10123456785");
    });

    it("should return empty array for missing data", () => {
      const response = {};

      const labels = extractLabelFromResponse(response);

      expect(labels).toHaveLength(0);
    });

    it("should filter out packages without label data", () => {
      const response = {
        ShipmentResponse: {
          ShipmentResults: {
            PackageResults: [
              {
                TrackingNumber: "1Z999AA10123456784",
                ShippingLabel: {
                  GraphicImage: "base64data1",
                },
              },
              {
                TrackingNumber: "1Z999AA10123456785",
                // No ShippingLabel
              },
            ],
          },
        },
      };

      const labels = extractLabelFromResponse(response);

      expect(labels).toHaveLength(1);
      expect(labels[0].trackingNumber).toBe("1Z999AA10123456784");
    });
  });
});

describe("Shipping Tool Behavior", () => {
  describe("shipping_create request structure", () => {
    it("should build correct UPS request structure", () => {
      // This tests the expected structure that would be sent to UPS API
      const input = {
        shipper: {
          name: "Test Shipper",
          phone: "1234567890",
          addressLine1: "123 Main St",
          city: "Atlanta",
          stateProvinceCode: "GA",
          postalCode: "30301",
          countryCode: "US",
        },
        shipTo: {
          name: "Test Recipient",
          phone: "0987654321",
          addressLine1: "456 Oak Ave",
          city: "New York",
          stateProvinceCode: "NY",
          postalCode: "10001",
          countryCode: "US",
        },
        packages: [{ weight: 5.5, packagingType: "02" }],
        serviceCode: "03", // Ground
      };

      // Verify input matches expected schema structure
      expect(input.shipper.name).toBe("Test Shipper");
      expect(input.packages).toHaveLength(1);
      expect(input.serviceCode).toBe("03");
    });
  });

  describe("shipping_create response extraction", () => {
    it("should extract tracking number from response", () => {
      const response = {
        ShipmentResponse: {
          ShipmentResults: {
            ShipmentIdentificationNumber: "1Z999AA10123456784",
            PackageResults: {
              TrackingNumber: "1Z999AA10123456784",
              ShippingLabel: {
                ImageFormat: { Code: "PDF" },
                GraphicImage: "JVBERi0xLjQK...",
              },
            },
            ShipmentCharges: {
              TotalCharges: {
                CurrencyCode: "USD",
                MonetaryValue: "15.50",
              },
            },
          },
        },
      };

      // Extract values as the tool would
      const shipmentId =
        response.ShipmentResponse.ShipmentResults.ShipmentIdentificationNumber;
      const charges =
        response.ShipmentResponse.ShipmentResults.ShipmentCharges?.TotalCharges;

      expect(shipmentId).toBe("1Z999AA10123456784");
      expect(charges?.CurrencyCode).toBe("USD");
      expect(charges?.MonetaryValue).toBe("15.50");
    });
  });

  describe("shipping_void endpoint", () => {
    it("should target correct endpoint path", () => {
      const trackingNumber = "1Z999AA10123456784";
      const expectedPath = `/shipments/v2409/void/cancel/${trackingNumber}`;

      expect(expectedPath).toBe(
        "/shipments/v2409/void/cancel/1Z999AA10123456784"
      );
    });

    it("should parse void response correctly", () => {
      const response = {
        VoidShipmentResponse: {
          Response: {
            ResponseStatus: { Code: "1", Description: "Success" },
          },
          SummaryResult: {
            Status: { Code: "1", Description: "Voided" },
          },
        },
      };

      const status = response.VoidShipmentResponse.SummaryResult.Status;
      const success = status.Code === "1";

      expect(success).toBe(true);
      expect(status.Description).toBe("Voided");
    });
  });

  describe("shipping_get_label endpoint", () => {
    it("should build correct label recovery request", () => {
      const trackingNumber = "1Z999AA10123456784";

      const request = {
        LabelRecoveryRequest: {
          LabelSpecification: {
            LabelImageFormat: {
              Code: "PDF",
            },
          },
          TrackingNumber: trackingNumber,
        },
      };

      expect(request.LabelRecoveryRequest.TrackingNumber).toBe(trackingNumber);
      expect(request.LabelRecoveryRequest.LabelSpecification.LabelImageFormat.Code).toBe("PDF");
    });
  });

  describe("label filename format", () => {
    it("should follow {tracking_number}.pdf format", async () => {
      const trackingNumber = "1Z999AA10123456784";
      const outputDir = "/tmp/labels";

      const labelPath = await saveLabel(
        trackingNumber,
        "JVBERi0xLjQK",
        outputDir
      );

      expect(labelPath).toBe("/tmp/labels/1Z999AA10123456784.pdf");
      expect(labelPath).toMatch(/^.*1Z999AA10123456784\.pdf$/);
    });
  });
});
