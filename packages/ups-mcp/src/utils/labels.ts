/**
 * Label Handling Utilities
 *
 * Provides utilities for decoding and saving PDF shipping labels.
 * Per CONTEXT.md Decision 3:
 * - PDF only format
 * - Filename format: {tracking_number}.pdf
 * - Flat directory structure (no subdirectories)
 * - MCP saves labels directly
 */

import { writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";

/**
 * Label extraction result from UPS shipment response
 */
export interface ExtractedLabel {
  trackingNumber: string;
  base64Data: string;
}

/**
 * Save a Base64-encoded PDF label to the filesystem.
 *
 * Creates the output directory if it doesn't exist.
 * Overwrites existing file if present.
 *
 * @param trackingNumber - UPS tracking number (used as filename)
 * @param base64Data - Base64-encoded PDF content
 * @param outputDir - Directory to save labels to
 * @returns Full path to saved label file
 */
export async function saveLabel(
  trackingNumber: string,
  base64Data: string,
  outputDir: string
): Promise<string> {
  // Ensure output directory exists
  await mkdir(outputDir, { recursive: true });

  // Decode Base64 to binary
  const buffer = Buffer.from(base64Data, "base64");

  // Build file path: {outputDir}/{trackingNumber}.pdf
  const filePath = join(outputDir, `${trackingNumber}.pdf`);

  // Write file
  await writeFile(filePath, buffer);

  return filePath;
}

/**
 * Extract labels from UPS shipment response.
 *
 * UPS returns labels in:
 * ShipmentResponse.ShipmentResults.PackageResults[].ShippingLabel.GraphicImage
 *
 * Handles both single package (object) and multi-package (array) responses.
 *
 * @param response - Raw UPS API response object
 * @returns Array of extracted labels with tracking numbers and Base64 data
 */
export function extractLabelFromResponse(
  response: unknown
): ExtractedLabel[] {
  // Type guard for response structure
  const shipmentResponse = response as {
    ShipmentResponse?: {
      ShipmentResults?: {
        PackageResults?: unknown;
      };
    };
  };

  const packageResults =
    shipmentResponse?.ShipmentResponse?.ShipmentResults?.PackageResults;

  if (!packageResults) {
    return [];
  }

  // Normalize to array (UPS returns object for single package, array for multiple)
  const results = Array.isArray(packageResults)
    ? packageResults
    : [packageResults];

  return results
    .map((pkg: unknown) => {
      const typedPkg = pkg as {
        TrackingNumber?: string;
        ShippingLabel?: {
          GraphicImage?: string;
        };
      };

      return {
        trackingNumber: typedPkg?.TrackingNumber ?? "",
        base64Data: typedPkg?.ShippingLabel?.GraphicImage ?? "",
      };
    })
    .filter(
      (item): item is ExtractedLabel =>
        item.trackingNumber !== "" && item.base64Data !== ""
    );
}
