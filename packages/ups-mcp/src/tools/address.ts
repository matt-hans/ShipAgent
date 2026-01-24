/**
 * Address Validation Tool for UPS MCP
 *
 * Provides address_validate tool for verifying addresses with UPS API.
 * Returns standardized addresses, candidate suggestions for ambiguous addresses,
 * or clear reasons for invalid addresses.
 *
 * Per CONTEXT.md: This is a separate tool - shipping_create does NOT auto-validate.
 * Users compose validation into their workflow as needed.
 */

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { UpsApiClient } from "../client/api.js";

/**
 * Input schema for address_validate tool
 */
const AddressValidationInputSchema = z.object({
  addressLine1: z.string().describe("Street address line 1"),
  addressLine2: z.string().optional().describe("Street address line 2"),
  city: z.string().describe("City name"),
  stateProvinceCode: z.string().describe("State/province code (e.g., CA, NY)"),
  postalCode: z.string().describe("Postal/ZIP code"),
  countryCode: z.string().default("US").describe("Country code"),
});

/**
 * Address structure returned in validation results
 */
const ValidatedAddressSchema = z.object({
  addressLine1: z.string(),
  addressLine2: z.string().optional(),
  city: z.string(),
  stateProvinceCode: z.string(),
  postalCode: z.string(),
  countryCode: z.string(),
});

/**
 * Candidate address with optional classification
 */
const CandidateAddressSchema = ValidatedAddressSchema.extend({
  classification: z.enum(["commercial", "residential", "unknown"]).optional(),
});

/**
 * Output schema for address_validate tool
 */
const AddressValidationOutputSchema = z.object({
  status: z.enum(["valid", "ambiguous", "invalid"]),
  classification: z.enum(["commercial", "residential", "unknown"]).optional(),
  validatedAddress: ValidatedAddressSchema.optional(),
  candidates: z.array(CandidateAddressSchema).optional(),
  invalidReason: z.string().optional(),
});

/**
 * Type for validated input
 */
type AddressValidationInput = z.infer<typeof AddressValidationInputSchema>;

/**
 * Type for tool output
 */
type AddressValidationOutput = z.infer<typeof AddressValidationOutputSchema>;

/**
 * UPS Address Classification Codes
 * 0 = Unknown, 1 = Commercial, 2 = Residential
 */
const CLASSIFICATION_MAP: Record<string, "commercial" | "residential" | "unknown"> = {
  "0": "unknown",
  "1": "commercial",
  "2": "residential",
};

/**
 * UPS Address Validation API response structure
 */
interface UpsXAVResponse {
  XAVResponse: {
    ValidAddressIndicator?: string;
    AmbiguousAddressIndicator?: string;
    NoCandidatesIndicator?: string;
    Candidate?: UpsCandidate | UpsCandidate[];
  };
}

/**
 * UPS Candidate address structure
 */
interface UpsCandidate {
  AddressClassification?: {
    Code?: string;
    Description?: string;
  };
  AddressLine?: string | string[];
  PoliticalDivision2?: string; // City
  PoliticalDivision1?: string; // State
  PostcodePrimaryLow?: string;
  PostcodeExtendedLow?: string;
  CountryCode?: string;
}

/**
 * Maps UPS classification code to our classification type
 */
function mapClassification(code: string | undefined): "commercial" | "residential" | "unknown" {
  if (!code) return "unknown";
  return CLASSIFICATION_MAP[code] ?? "unknown";
}

/**
 * Converts UPS candidate to our address format
 */
function mapCandidate(candidate: UpsCandidate): z.infer<typeof CandidateAddressSchema> {
  // AddressLine can be a string or array
  const addressLines = Array.isArray(candidate.AddressLine)
    ? candidate.AddressLine
    : candidate.AddressLine
      ? [candidate.AddressLine]
      : [];

  // Build postal code with optional extension
  let postalCode = candidate.PostcodePrimaryLow ?? "";
  if (candidate.PostcodeExtendedLow) {
    postalCode = `${postalCode}-${candidate.PostcodeExtendedLow}`;
  }

  return {
    addressLine1: addressLines[0] ?? "",
    addressLine2: addressLines[1] ?? undefined,
    city: candidate.PoliticalDivision2 ?? "",
    stateProvinceCode: candidate.PoliticalDivision1 ?? "",
    postalCode,
    countryCode: candidate.CountryCode ?? "US",
    classification: mapClassification(candidate.AddressClassification?.Code),
  };
}

/**
 * Builds UPS Address Validation request body
 */
function buildXAVRequest(input: AddressValidationInput): object {
  const addressLines = [input.addressLine1];
  if (input.addressLine2) {
    addressLines.push(input.addressLine2);
  }

  return {
    XAVRequest: {
      AddressKeyFormat: {
        AddressLine: addressLines,
        PoliticalDivision2: input.city,
        PoliticalDivision1: input.stateProvinceCode,
        PostcodePrimaryLow: input.postalCode,
        CountryCode: input.countryCode,
      },
    },
  };
}

/**
 * Parses UPS XAV response to determine validation status and result
 */
function parseXAVResponse(response: UpsXAVResponse): AddressValidationOutput {
  const xav = response.XAVResponse;

  // No candidates - invalid address
  if (xav.NoCandidatesIndicator !== undefined) {
    return {
      status: "invalid",
      invalidReason: "No valid address match found. Please verify the address details.",
    };
  }

  // Normalize candidates to array
  const candidates = xav.Candidate
    ? Array.isArray(xav.Candidate)
      ? xav.Candidate
      : [xav.Candidate]
    : [];

  // No candidates in response
  if (candidates.length === 0) {
    return {
      status: "invalid",
      invalidReason: "No address candidates returned from UPS.",
    };
  }

  // Ambiguous - multiple candidates
  if (xav.AmbiguousAddressIndicator !== undefined || candidates.length > 1) {
    return {
      status: "ambiguous",
      candidates: candidates.map(mapCandidate),
    };
  }

  // Valid - single exact match
  if (xav.ValidAddressIndicator !== undefined || candidates.length === 1) {
    const validated = mapCandidate(candidates[0]);
    const { classification, ...validatedAddress } = validated;

    return {
      status: "valid",
      classification,
      validatedAddress,
    };
  }

  // Fallback - shouldn't reach here
  return {
    status: "invalid",
    invalidReason: "Unexpected response from UPS Address Validation API.",
  };
}

/**
 * Registers address validation tools with the MCP server
 *
 * @param server - MCP server instance
 * @param apiClient - UPS API client for making requests
 */
export function registerAddressTools(
  server: McpServer,
  apiClient: UpsApiClient
): void {
  server.tool(
    "address_validate",
    "Validate an address with UPS. Returns standardized address for valid addresses, " +
      "candidate suggestions for ambiguous addresses, or clear reason for invalid addresses.",
    AddressValidationInputSchema.shape,
    async (params): Promise<{ content: Array<{ type: "text"; text: string }>; structuredContent: AddressValidationOutput }> => {
      // Parse and validate input
      const input = AddressValidationInputSchema.parse(params);

      // Build request
      const requestBody = buildXAVRequest(input);

      // Call UPS Address Validation API
      // Request option "1" = Address Validation
      const response = await apiClient.post<UpsXAVResponse>(
        "/addressvalidation/v2/1",
        requestBody
      );

      // Parse response
      const output = parseXAVResponse(response);

      return {
        content: [{ type: "text", text: JSON.stringify(output, null, 2) }],
        structuredContent: output,
      };
    }
  );
}
