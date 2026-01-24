/**
 * UPS Shipping API Zod Schemas
 *
 * Manually crafted schemas based on UPS OpenAPI specification (shipping.yaml).
 * These schemas cover the core types needed for shipment creation, validation,
 * and response handling.
 *
 * Reference: https://developer.ups.com/api/reference/shipping
 */

import { z } from "zod";

// ============================================================================
// Common Types
// ============================================================================

/**
 * UPS Transaction Reference for request tracking
 */
export const TransactionReferenceSchema = z
  .object({
    CustomerContext: z.string().max(512).optional(),
  })
  .passthrough();

export type TransactionReference = z.infer<typeof TransactionReferenceSchema>;

/**
 * Request metadata
 */
export const RequestSchema = z
  .object({
    RequestOption: z.string().max(15).optional(),
    SubVersion: z.string().length(4).optional(),
    TransactionReference: TransactionReferenceSchema.optional(),
  })
  .passthrough();

export type Request = z.infer<typeof RequestSchema>;

/**
 * Phone number
 */
export const PhoneSchema = z
  .object({
    Number: z.string().min(1).max(15),
    Extension: z.string().max(4).optional(),
  })
  .passthrough();

export type Phone = z.infer<typeof PhoneSchema>;

/**
 * Address schema - used by shipper, ship-to, ship-from
 */
export const AddressSchema = z
  .object({
    AddressLine: z.array(z.string().max(35)).min(1).max(3),
    City: z.string().min(1).max(30),
    StateProvinceCode: z.string().max(5).optional(),
    PostalCode: z.string().max(9).optional(),
    CountryCode: z.string().length(2),
    ResidentialAddressIndicator: z.string().optional(),
  })
  .passthrough();

export type Address = z.infer<typeof AddressSchema>;

// ============================================================================
// Shipper, ShipTo, ShipFrom
// ============================================================================

/**
 * Shipper information
 */
export const ShipperSchema = z
  .object({
    Name: z.string().min(1).max(35),
    AttentionName: z.string().max(35).optional(),
    CompanyDisplayableName: z.string().max(35).optional(),
    TaxIdentificationNumber: z.string().max(15).optional(),
    Phone: PhoneSchema.optional(),
    ShipperNumber: z.string().length(6),
    FaxNumber: z.string().max(14).optional(),
    EMailAddress: z.string().max(50).optional(),
    Address: AddressSchema,
  })
  .passthrough();

export type Shipper = z.infer<typeof ShipperSchema>;

/**
 * Ship-to (recipient) information
 */
export const ShipToSchema = z
  .object({
    Name: z.string().min(1).max(35),
    AttentionName: z.string().max(35).optional(),
    CompanyDisplayableName: z.string().max(35).optional(),
    TaxIdentificationNumber: z.string().max(15).optional(),
    Phone: PhoneSchema.optional(),
    FaxNumber: z.string().max(15).optional(),
    EMailAddress: z.string().max(50).optional(),
    Address: AddressSchema,
    LocationID: z.string().max(10).optional(),
  })
  .passthrough();

export type ShipTo = z.infer<typeof ShipToSchema>;

/**
 * Ship-from (origin) information
 */
export const ShipFromSchema = z
  .object({
    Name: z.string().min(1).max(35),
    AttentionName: z.string().max(35).optional(),
    CompanyDisplayableName: z.string().max(35).optional(),
    TaxIdentificationNumber: z.string().max(15).optional(),
    Phone: PhoneSchema.optional(),
    FaxNumber: z.string().max(15).optional(),
    Address: AddressSchema,
  })
  .passthrough();

export type ShipFrom = z.infer<typeof ShipFromSchema>;

// ============================================================================
// Payment Information
// ============================================================================

/**
 * Bill shipper payment
 */
export const BillShipperSchema = z
  .object({
    AccountNumber: z.string().length(6),
  })
  .passthrough();

export type BillShipper = z.infer<typeof BillShipperSchema>;

/**
 * Shipment charge
 */
export const ShipmentChargeSchema = z
  .object({
    Type: z.string().min(1).max(2), // "01" = Transportation, "02" = Duties and Taxes
    BillShipper: BillShipperSchema.optional(),
  })
  .passthrough();

export type ShipmentCharge = z.infer<typeof ShipmentChargeSchema>;

/**
 * Payment information
 */
export const PaymentInformationSchema = z
  .object({
    ShipmentCharge: z.union([
      ShipmentChargeSchema,
      z.array(ShipmentChargeSchema),
    ]),
  })
  .passthrough();

export type PaymentInformation = z.infer<typeof PaymentInformationSchema>;

// ============================================================================
// Service and Package
// ============================================================================

/**
 * UPS Service code and description
 * Common codes: "01" = Next Day Air, "02" = 2nd Day Air, "03" = Ground
 */
export const ServiceSchema = z
  .object({
    Code: z.string().min(1).max(2),
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type Service = z.infer<typeof ServiceSchema>;

/**
 * Unit of measurement
 */
export const UnitOfMeasurementSchema = z
  .object({
    Code: z.string().min(1).max(3), // "LBS", "KGS", "IN", "CM"
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type UnitOfMeasurement = z.infer<typeof UnitOfMeasurementSchema>;

/**
 * Package dimensions
 */
export const DimensionsSchema = z
  .object({
    UnitOfMeasurement: UnitOfMeasurementSchema,
    Length: z.string().min(1).max(8),
    Width: z.string().min(1).max(8),
    Height: z.string().min(1).max(8),
  })
  .passthrough();

export type Dimensions = z.infer<typeof DimensionsSchema>;

/**
 * Package weight
 */
export const PackageWeightSchema = z
  .object({
    UnitOfMeasurement: UnitOfMeasurementSchema,
    Weight: z.string().min(1).max(8),
  })
  .passthrough();

export type PackageWeight = z.infer<typeof PackageWeightSchema>;

/**
 * Packaging type
 * Common codes: "01" = UPS Letter, "02" = Customer Supplied Package
 */
export const PackagingSchema = z
  .object({
    Code: z.string().min(1).max(2),
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type Packaging = z.infer<typeof PackagingSchema>;

/**
 * Package service options (optional services per package)
 */
export const PackageServiceOptionsSchema = z
  .object({
    DeliveryConfirmation: z
      .object({
        DCISType: z.string().min(1).max(1), // "1" = Delivery Confirmation, "2" = Signature Required
      })
      .passthrough()
      .optional(),
    DeclaredValue: z
      .object({
        CurrencyCode: z.string().length(3),
        MonetaryValue: z.string().min(1).max(15),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

export type PackageServiceOptions = z.infer<typeof PackageServiceOptionsSchema>;

/**
 * Package details
 */
export const PackageSchema = z
  .object({
    Description: z.string().max(35).optional(),
    Packaging: PackagingSchema,
    Dimensions: DimensionsSchema.optional(),
    PackageWeight: PackageWeightSchema,
    PackageServiceOptions: PackageServiceOptionsSchema.optional(),
    NumOfPieces: z.string().max(5).optional(),
  })
  .passthrough();

export type Package = z.infer<typeof PackageSchema>;

// ============================================================================
// Label Specification
// ============================================================================

/**
 * Label image format
 * Codes: "GIF", "PNG", "ZPL", "EPL", "PDF"
 */
export const LabelImageFormatSchema = z
  .object({
    Code: z.string().min(1).max(3),
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type LabelImageFormat = z.infer<typeof LabelImageFormatSchema>;

/**
 * Label specification
 */
export const LabelSpecificationSchema = z
  .object({
    LabelImageFormat: LabelImageFormatSchema,
    HTTPUserAgent: z.string().max(64).optional(),
    LabelStockSize: z
      .object({
        Height: z.string().min(1).max(4),
        Width: z.string().min(1).max(4),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

export type LabelSpecification = z.infer<typeof LabelSpecificationSchema>;

// ============================================================================
// Shipment Request
// ============================================================================

/**
 * Shipment details
 */
export const ShipmentSchema = z.object({
  Description: z.string().max(35).optional(),
  Shipper: ShipperSchema,
  ShipTo: ShipToSchema,
  ShipFrom: ShipFromSchema.optional(),
  PaymentInformation: PaymentInformationSchema,
  Service: ServiceSchema,
  Package: z.union([PackageSchema, z.array(PackageSchema)]),
  ShipmentRatingOptions: z
    .object({
      NegotiatedRatesIndicator: z.string().optional(),
    })
    .optional(),
});

export type Shipment = z.infer<typeof ShipmentSchema>;

/**
 * Shipment request wrapper
 */
export const ShipmentRequestSchema = z.object({
  Request: RequestSchema.optional(),
  Shipment: ShipmentSchema,
  LabelSpecification: LabelSpecificationSchema,
});

export type ShipmentRequest = z.infer<typeof ShipmentRequestSchema>;

/**
 * Full UPS API request wrapper
 */
export const ShipRequestWrapperSchema = z.object({
  ShipmentRequest: ShipmentRequestSchema,
});

export type ShipRequestWrapper = z.infer<typeof ShipRequestWrapperSchema>;

// ============================================================================
// Shipment Response
// ============================================================================

/**
 * Response status
 */
export const ResponseStatusSchema = z
  .object({
    Code: z.string(),
    Description: z.string(),
  })
  .passthrough();

export type ResponseStatus = z.infer<typeof ResponseStatusSchema>;

/**
 * Response metadata
 */
export const ResponseSchema = z
  .object({
    ResponseStatus: ResponseStatusSchema,
    Alert: z
      .array(
        z
          .object({
            Code: z.string(),
            Description: z.string(),
          })
          .passthrough()
      )
      .optional(),
    TransactionReference: TransactionReferenceSchema.optional(),
  })
  .passthrough();

export type Response = z.infer<typeof ResponseSchema>;

/**
 * Package result from shipment response
 */
export const PackageResultSchema = z
  .object({
    TrackingNumber: z.string(),
    ShippingLabel: z
      .object({
        ImageFormat: z
          .object({
            Code: z.string(),
            Description: z.string().optional(),
          })
          .passthrough(),
        GraphicImage: z.string(), // Base64 encoded label image
        HTMLImage: z.string().optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

export type PackageResult = z.infer<typeof PackageResultSchema>;

/**
 * Shipment charge details in response
 */
export const ShipmentChargesSchema = z
  .object({
    TransportationCharges: z
      .object({
        CurrencyCode: z.string(),
        MonetaryValue: z.string(),
      })
      .passthrough()
      .optional(),
    ServiceOptionsCharges: z
      .object({
        CurrencyCode: z.string(),
        MonetaryValue: z.string(),
      })
      .passthrough()
      .optional(),
    TotalCharges: z
      .object({
        CurrencyCode: z.string(),
        MonetaryValue: z.string(),
      })
      .passthrough(),
  })
  .passthrough();

export type ShipmentCharges = z.infer<typeof ShipmentChargesSchema>;

/**
 * Shipment results in response
 */
export const ShipmentResultsSchema = z
  .object({
    ShipmentIdentificationNumber: z.string(),
    PackageResults: z.union([PackageResultSchema, z.array(PackageResultSchema)]),
    ShipmentCharges: ShipmentChargesSchema.optional(),
    NegotiatedRateCharges: z
      .object({
        TotalCharge: z
          .object({
            CurrencyCode: z.string(),
            MonetaryValue: z.string(),
          })
          .passthrough(),
      })
      .passthrough()
      .optional(),
    BillingWeight: z
      .object({
        UnitOfMeasurement: UnitOfMeasurementSchema,
        Weight: z.string(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

export type ShipmentResults = z.infer<typeof ShipmentResultsSchema>;

/**
 * Shipment response
 */
export const ShipmentResponseSchema = z
  .object({
    Response: ResponseSchema,
    ShipmentResults: ShipmentResultsSchema,
  })
  .passthrough();

export type ShipmentResponse = z.infer<typeof ShipmentResponseSchema>;

/**
 * Full UPS API response wrapper
 */
export const ShipResponseWrapperSchema = z
  .object({
    ShipmentResponse: ShipmentResponseSchema,
  })
  .passthrough();

export type ShipResponseWrapper = z.infer<typeof ShipResponseWrapperSchema>;

// ============================================================================
// Void Shipment
// ============================================================================

/**
 * Void shipment response
 */
export const VoidShipmentResponseSchema = z
  .object({
    Response: ResponseSchema,
    SummaryResult: z
      .object({
        Status: z
          .object({
            Code: z.string(),
            Description: z.string(),
          })
          .passthrough(),
      })
      .passthrough(),
  })
  .passthrough();

export type VoidShipmentResponse = z.infer<typeof VoidShipmentResponseSchema>;

// ============================================================================
// Error Response
// ============================================================================

/**
 * Error detail
 */
export const ErrorDetailSchema = z
  .object({
    Code: z.string(),
    Message: z.string(),
  })
  .passthrough();

export type ErrorDetail = z.infer<typeof ErrorDetailSchema>;

/**
 * UPS API error response
 */
export const ErrorResponseSchema = z
  .object({
    response: z
      .object({
        errors: z.array(ErrorDetailSchema),
      })
      .passthrough(),
  })
  .passthrough();

export type ErrorResponse = z.infer<typeof ErrorResponseSchema>;
