/**
 * Debug script to gather evidence about UPS API responses
 */
import { UpsAuthManager } from "./src/auth/manager.js";
import { UpsApiClient } from "./src/client/api.js";

const UPS_SANDBOX_BASE_URL = "https://wwwcie.ups.com/api";

const testShipFrom = {
  name: "Test Shipper Inc",
  attentionName: "John Sender",
  phone: "4155551234",
  addressLine1: "1400 16th St",
  city: "San Francisco",
  stateProvinceCode: "CA",
  postalCode: "94103",
  countryCode: "US",
};

const testShipTo = {
  name: "Test Recipient LLC",
  attentionName: "Jane Receiver",
  phone: "2125551234",
  addressLine1: "350 5th Ave",
  city: "New York",
  stateProvinceCode: "NY",
  postalCode: "10118",
  countryCode: "US",
};

async function debugRatingQuote() {
  console.log("\n=== DEBUG: rating_quote ===");
  
  const authManager = new UpsAuthManager(
    process.env.UPS_CLIENT_ID!,
    process.env.UPS_CLIENT_SECRET!,
    "https://wwwcie.ups.com/security/v1/oauth/token"
  );
  const apiClient = new UpsApiClient(authManager, UPS_SANDBOX_BASE_URL);
  const accountNumber = process.env.UPS_ACCOUNT_NUMBER!;

  const requestBody = {
    RateRequest: {
      Request: {
        SubVersion: "2403",
      },
      Shipment: {
        Shipper: {
          Name: testShipFrom.name,
          ShipperNumber: accountNumber,
          Address: {
            AddressLine: [testShipFrom.addressLine1],
            City: testShipFrom.city,
            StateProvinceCode: testShipFrom.stateProvinceCode,
            PostalCode: testShipFrom.postalCode,
            CountryCode: testShipFrom.countryCode,
          },
        },
        ShipTo: {
          Name: testShipTo.name,
          Address: {
            AddressLine: [testShipTo.addressLine1],
            City: testShipTo.city,
            StateProvinceCode: testShipTo.stateProvinceCode,
            PostalCode: testShipTo.postalCode,
            CountryCode: testShipTo.countryCode,
          },
        },
        ShipFrom: {
          Name: testShipFrom.name,
          Address: {
            AddressLine: [testShipFrom.addressLine1],
            City: testShipFrom.city,
            StateProvinceCode: testShipFrom.stateProvinceCode,
            PostalCode: testShipFrom.postalCode,
            CountryCode: testShipFrom.countryCode,
          },
        },
        Service: {
          Code: "03", // UPS Ground
        },
        Package: {
          PackagingType: {
            Code: "02",
          },
          PackageWeight: {
            UnitOfMeasurement: {
              Code: "LBS",
            },
            Weight: "5",
          },
          Dimensions: {
            UnitOfMeasurement: {
              Code: "IN",
            },
            Length: "10",
            Width: "8",
            Height: "6",
          },
        },
        PaymentDetails: {
          ShipmentCharge: {
            Type: "01",
            BillShipper: {
              AccountNumber: accountNumber,
            },
          },
        },
      },
    },
  };

  console.log("Request URL: /rating/v2403/Rate");
  console.log("Account Number:", accountNumber);
  
  try {
    const response = await apiClient.post<any>("/rating/v2403/Rate", requestBody);
    console.log("Response received successfully");
    console.log("Full response:", JSON.stringify(response, null, 2));
    
    // Check structure
    console.log("\n--- Response Structure ---");
    console.log("Has RateResponse:", "RateResponse" in response);
    if (response.RateResponse) {
      console.log("Has RatedShipment:", "RatedShipment" in response.RateResponse);
      console.log("RatedShipment type:", typeof response.RateResponse.RatedShipment);
      console.log("RatedShipment is array:", Array.isArray(response.RateResponse.RatedShipment));
    }
  } catch (error: any) {
    console.log("Error occurred:", error.message);
    if (error.response) {
      console.log("Error response:", JSON.stringify(error.response, null, 2));
    }
  }
}

async function debugAddressValidate() {
  console.log("\n=== DEBUG: address_validate ===");
  
  const authManager = new UpsAuthManager(
    process.env.UPS_CLIENT_ID!,
    process.env.UPS_CLIENT_SECRET!,
    "https://wwwcie.ups.com/security/v1/oauth/token"
  );
  const apiClient = new UpsApiClient(authManager, UPS_SANDBOX_BASE_URL);

  const requestBody = {
    XAVRequest: {
      AddressKeyFormat: {
        AddressLine: [testShipTo.addressLine1],
        PoliticalDivision2: testShipTo.city,
        PoliticalDivision1: testShipTo.stateProvinceCode,
        PostcodePrimaryLow: testShipTo.postalCode,
        CountryCode: testShipTo.countryCode,
      },
    },
  };

  console.log("Request URL: /addressvalidation/v2/1");
  console.log("Request body:", JSON.stringify(requestBody, null, 2));
  
  try {
    const response = await apiClient.post<any>("/addressvalidation/v2/1", requestBody);
    console.log("Response received successfully");
    console.log("Full response:", JSON.stringify(response, null, 2));
  } catch (error: any) {
    console.log("Error occurred:", error.message);
    console.log("Error code:", error.code);
    console.log("Full error:", JSON.stringify(error, null, 2));
  }
}

async function main() {
  console.log("Starting UPS API debugging...");
  console.log("UPS_CLIENT_ID:", process.env.UPS_CLIENT_ID?.substring(0, 10) + "...");
  console.log("UPS_ACCOUNT_NUMBER:", process.env.UPS_ACCOUNT_NUMBER);
  
  await debugRatingQuote();
  await debugAddressValidate();
}

main().catch(console.error);
