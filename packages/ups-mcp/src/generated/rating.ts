/**
 * UPS Rating API Zod Schemas
 *
 * Manually crafted schemas based on UPS OpenAPI specification (rating.yaml).
 * These schemas cover the core types needed for rate quotes, shopping rates,
 * and time-in-transit.
 *
 * Reference: https://developer.ups.com/api/reference/rating
 */

import { z } from "zod";

// ============================================================================
// Common Types (re-export from shipping for consistency)
// ============================================================================

/**
 * Transaction reference for request tracking
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
export const RateRequestMetadataSchema = z
  .object({
    SubVersion: z.string().length(4).optional(),
    TransactionReference: TransactionReferenceSchema.optional(),
  })
  .passthrough();

export type RateRequestMetadata = z.infer<typeof RateRequestMetadataSchema>;

/**
 * Address schema for rating
 */
export const RateAddressSchema = z
  .object({
    AddressLine: z.array(z.string().max(35)).optional(),
    City: z.string().max(30).optional(),
    StateProvinceCode: z.string().max(5).optional(),
    PostalCode: z.string().max(9).optional(),
    CountryCode: z.string().length(2),
    ResidentialAddressIndicator: z.string().optional(),
  })
  .passthrough();

export type RateAddress = z.infer<typeof RateAddressSchema>;

// ============================================================================
// Shipper, ShipTo, ShipFrom for Rating
// ============================================================================

/**
 * Shipper for rate request (fewer required fields than shipping)
 */
export const RateShipperSchema = z
  .object({
    Name: z.string().max(35).optional(),
    AttentionName: z.string().max(35).optional(),
    ShipperNumber: z.string().length(6).optional(),
    Address: RateAddressSchema,
  })
  .passthrough();

export type RateShipper = z.infer<typeof RateShipperSchema>;

/**
 * Ship-to for rate request
 */
export const RateShipToSchema = z
  .object({
    Name: z.string().max(35).optional(),
    AttentionName: z.string().max(35).optional(),
    Address: RateAddressSchema,
  })
  .passthrough();

export type RateShipTo = z.infer<typeof RateShipToSchema>;

/**
 * Ship-from for rate request
 */
export const RateShipFromSchema = z
  .object({
    Name: z.string().max(35).optional(),
    AttentionName: z.string().max(35).optional(),
    Address: RateAddressSchema,
  })
  .passthrough();

export type RateShipFrom = z.infer<typeof RateShipFromSchema>;

// ============================================================================
// Package for Rating
// ============================================================================

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
 * Package dimensions for rating
 */
export const RateDimensionsSchema = z
  .object({
    UnitOfMeasurement: UnitOfMeasurementSchema,
    Length: z.string().max(8),
    Width: z.string().max(8),
    Height: z.string().max(8),
  })
  .passthrough();

export type RateDimensions = z.infer<typeof RateDimensionsSchema>;

/**
 * Package weight for rating
 */
export const RatePackageWeightSchema = z
  .object({
    UnitOfMeasurement: UnitOfMeasurementSchema,
    Weight: z.string().max(8),
  })
  .passthrough();

export type RatePackageWeight = z.infer<typeof RatePackageWeightSchema>;

/**
 * Packaging type
 */
export const RatePackagingTypeSchema = z
  .object({
    Code: z.string().max(2),
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type RatePackagingType = z.infer<typeof RatePackagingTypeSchema>;

/**
 * Package for rate request
 */
export const RatePackageSchema = z
  .object({
    PackagingType: RatePackagingTypeSchema.optional(),
    Dimensions: RateDimensionsSchema.optional(),
    PackageWeight: RatePackageWeightSchema,
    PackageServiceOptions: z.object({}).passthrough().optional(),
    NumOfPieces: z.string().max(5).optional(),
  })
  .passthrough();

export type RatePackage = z.infer<typeof RatePackageSchema>;

// ============================================================================
// Service for Rating
// ============================================================================

/**
 * Service code for rate request
 * Common codes: "01" = Next Day Air, "02" = 2nd Day Air, "03" = Ground
 */
export const RateServiceSchema = z
  .object({
    Code: z.string().max(2),
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type RateService = z.infer<typeof RateServiceSchema>;

// ============================================================================
// Payment Details for Rating
// ============================================================================

/**
 * Bill shipper for rating
 */
export const RateBillShipperSchema = z
  .object({
    AccountNumber: z.string().length(6),
  })
  .passthrough();

export type RateBillShipper = z.infer<typeof RateBillShipperSchema>;

/**
 * Shipment charge for rating
 */
export const RateShipmentChargeSchema = z
  .object({
    Type: z.string().max(2),
    BillShipper: RateBillShipperSchema.optional(),
  })
  .passthrough();

export type RateShipmentCharge = z.infer<typeof RateShipmentChargeSchema>;

/**
 * Payment details for rate request
 */
export const RatePaymentDetailsSchema = z
  .object({
    ShipmentCharge: z.union([
      RateShipmentChargeSchema,
      z.array(RateShipmentChargeSchema),
    ]),
  })
  .passthrough();

export type RatePaymentDetails = z.infer<typeof RatePaymentDetailsSchema>;

// ============================================================================
// Rate Request
// ============================================================================

/**
 * Pickup type
 * Common codes: "01" = Daily Pickup, "03" = Customer Counter
 */
export const PickupTypeSchema = z
  .object({
    Code: z.string().max(2),
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type PickupType = z.infer<typeof PickupTypeSchema>;

/**
 * Customer classification
 * Codes: "00" = Rates Associated with Shipper Number, "01" = Daily Rates, etc.
 */
export const CustomerClassificationSchema = z
  .object({
    Code: z.string().max(2),
    Description: z.string().max(35).optional(),
  })
  .passthrough();

export type CustomerClassification = z.infer<typeof CustomerClassificationSchema>;

/**
 * Shipment rating options
 */
export const ShipmentRatingOptionsSchema = z
  .object({
    NegotiatedRatesIndicator: z.string().optional(),
    FRSShipmentIndicator: z.string().optional(),
    RateChartIndicator: z.string().optional(),
  })
  .passthrough();

export type ShipmentRatingOptions = z.infer<typeof ShipmentRatingOptionsSchema>;

/**
 * Shipment for rate request
 */
export const RateShipmentSchema = z.object({
  Shipper: RateShipperSchema,
  ShipTo: RateShipToSchema,
  ShipFrom: RateShipFromSchema.optional(),
  PaymentDetails: RatePaymentDetailsSchema.optional(),
  Service: RateServiceSchema.optional(), // Optional for Shop requests
  Package: z.union([RatePackageSchema, z.array(RatePackageSchema)]),
  ShipmentRatingOptions: ShipmentRatingOptionsSchema.optional(),
  NumOfPieces: z.string().max(5).optional(),
});

export type RateShipment = z.infer<typeof RateShipmentSchema>;

/**
 * Rate request
 */
export const RateRequestSchema = z.object({
  Request: RateRequestMetadataSchema.optional(),
  PickupType: PickupTypeSchema.optional(),
  CustomerClassification: CustomerClassificationSchema.optional(),
  Shipment: RateShipmentSchema,
});

export type RateRequest = z.infer<typeof RateRequestSchema>;

/**
 * Full UPS API rate request wrapper
 */
export const RateRequestWrapperSchema = z.object({
  RateRequest: RateRequestSchema,
});

export type RateRequestWrapper = z.infer<typeof RateRequestWrapperSchema>;

// ============================================================================
// Rate Response
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
 * Alert in response
 */
export const AlertSchema = z
  .object({
    Code: z.string(),
    Description: z.string(),
  })
  .passthrough();

export type Alert = z.infer<typeof AlertSchema>;

/**
 * Response metadata
 */
export const RateResponseMetadataSchema = z
  .object({
    ResponseStatus: ResponseStatusSchema,
    Alert: z.array(AlertSchema).optional(),
    TransactionReference: TransactionReferenceSchema.optional(),
  })
  .passthrough();

export type RateResponseMetadata = z.infer<typeof RateResponseMetadataSchema>;

/**
 * Monetary value with currency
 */
export const MonetaryValueSchema = z
  .object({
    CurrencyCode: z.string().length(3),
    MonetaryValue: z.string(),
  })
  .passthrough();

export type MonetaryValue = z.infer<typeof MonetaryValueSchema>;

/**
 * Total charges in rate response
 */
export const TotalChargesSchema = z
  .object({
    CurrencyCode: z.string(),
    MonetaryValue: z.string(),
  })
  .passthrough();

export type TotalCharges = z.infer<typeof TotalChargesSchema>;

/**
 * Itemized charges
 */
export const ItemizedChargesSchema = z
  .object({
    Code: z.string().optional(),
    CurrencyCode: z.string(),
    MonetaryValue: z.string(),
    SubType: z.string().optional(),
  })
  .passthrough();

export type ItemizedCharges = z.infer<typeof ItemizedChargesSchema>;

/**
 * Rated package in response
 */
export const RatedPackageSchema = z
  .object({
    TransportationCharges: TotalChargesSchema.optional(),
    ServiceOptionsCharges: TotalChargesSchema.optional(),
    TotalCharges: TotalChargesSchema.optional(),
    Weight: z.string().optional(),
    BillingWeight: z
      .object({
        UnitOfMeasurement: UnitOfMeasurementSchema,
        Weight: z.string(),
      })
      .passthrough()
      .optional(),
    ItemizedCharges: z.array(ItemizedChargesSchema).optional(),
  })
  .passthrough();

export type RatedPackage = z.infer<typeof RatedPackageSchema>;

/**
 * Time in transit information
 */
export const TimeInTransitSchema = z
  .object({
    PickupDate: z.string().optional(),
    DocumentsOnlyIndicator: z.string().optional(),
    PackageBillType: z.string().optional(),
    ServiceSummary: z
      .object({
        Service: z
          .object({
            Description: z.string().optional(),
          })
          .passthrough()
          .optional(),
        EstimatedArrival: z
          .object({
            Arrival: z
              .object({
                Date: z.string().optional(),
                Time: z.string().optional(),
              })
              .passthrough()
              .optional(),
            BusinessDaysInTransit: z.string().optional(),
            DayOfWeek: z.string().optional(),
          })
          .passthrough()
          .optional(),
        GuaranteedIndicator: z.string().optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

export type TimeInTransit = z.infer<typeof TimeInTransitSchema>;

/**
 * Negotiated rate charges
 */
export const NegotiatedRateChargesSchema = z
  .object({
    TotalCharge: TotalChargesSchema,
    TotalChargesWithTaxes: TotalChargesSchema.optional(),
    ItemizedCharges: z.array(ItemizedChargesSchema).optional(),
  })
  .passthrough();

export type NegotiatedRateCharges = z.infer<typeof NegotiatedRateChargesSchema>;

/**
 * Rated shipment in response
 */
export const RatedShipmentSchema = z
  .object({
    Service: z
      .object({
        Code: z.string(),
        Description: z.string().optional(),
      })
      .passthrough(),
    RatedShipmentAlert: z.array(AlertSchema).optional(),
    BillingWeight: z
      .object({
        UnitOfMeasurement: UnitOfMeasurementSchema,
        Weight: z.string(),
      })
      .passthrough()
      .optional(),
    TransportationCharges: TotalChargesSchema.optional(),
    BaseServiceCharge: TotalChargesSchema.optional(),
    ServiceOptionsCharges: TotalChargesSchema.optional(),
    TotalCharges: TotalChargesSchema,
    NegotiatedRateCharges: NegotiatedRateChargesSchema.optional(),
    RatedPackage: z.union([RatedPackageSchema, z.array(RatedPackageSchema)]).optional(),
    TimeInTransit: TimeInTransitSchema.optional(),
    GuaranteedDelivery: z
      .object({
        BusinessDaysInTransit: z.string().optional(),
        DeliveryByTime: z.string().optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

export type RatedShipment = z.infer<typeof RatedShipmentSchema>;

/**
 * Rate response
 */
export const RateResponseSchema = z.object({
  Response: RateResponseMetadataSchema,
  RatedShipment: z.union([RatedShipmentSchema, z.array(RatedShipmentSchema)]),
});

export type RateResponse = z.infer<typeof RateResponseSchema>;

/**
 * Full UPS API rate response wrapper
 */
export const RateResponseWrapperSchema = z.object({
  RateResponse: RateResponseSchema,
});

export type RateResponseWrapper = z.infer<typeof RateResponseWrapperSchema>;

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

// ============================================================================
// Service Code Constants
// ============================================================================

/**
 * UPS Service codes for reference
 */
export const UPS_SERVICE_CODES = {
  NEXT_DAY_AIR: "01",
  SECOND_DAY_AIR: "02",
  GROUND: "03",
  EXPRESS: "07",
  EXPEDITED: "08",
  STANDARD: "11",
  THREE_DAY_SELECT: "12",
  NEXT_DAY_AIR_SAVER: "13",
  UPS_NEXT_DAY_AIR_EARLY: "14",
  WORLDWIDE_ECONOMY_DDU: "17",
  WORLDWIDE_EXPRESS: "54",
  WORLDWIDE_SAVER: "65",
  SECOND_DAY_AIR_AM: "59",
  WORLDWIDE_EXPRESS_PLUS: "82",
  TODAY_STANDARD: "81",
  TODAY_DEDICATED_COURIER: "83",
  TODAY_INTERCITY: "84",
  TODAY_EXPRESS: "85",
  TODAY_EXPRESS_SAVER: "86",
  WORLDWIDE_EXPRESS_FREIGHT: "96",
} as const;

export type UPSServiceCode = (typeof UPS_SERVICE_CODES)[keyof typeof UPS_SERVICE_CODES];
