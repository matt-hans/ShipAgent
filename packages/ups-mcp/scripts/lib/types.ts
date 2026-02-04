/**
 * TypeScript interfaces for Shopify Test Order Generator
 *
 * Defines types for Shopify API requests/responses, address data,
 * progress tracking, and CLI configuration.
 */

// =============================================================================
// Shopify Order Types
// =============================================================================

/**
 * Shopify order financial status
 */
export type FinancialStatus = "paid" | "pending" | "refunded";

/**
 * Shopify order fulfillment status
 */
export type FulfillmentStatus = null | "partial" | "fulfilled";

/**
 * Shopify shipping address
 */
export interface ShopifyAddress {
  first_name: string;
  last_name: string;
  address1: string;
  address2?: string;
  city: string;
  province: string;
  province_code: string;
  zip: string;
  country: string;
  country_code: string;
  phone?: string;
}

/**
 * Shopify order line item
 */
export interface ShopifyLineItem {
  title: string;
  price: string;
  quantity: number;
  grams: number;
  requires_shipping: boolean;
  sku?: string;
}

/**
 * Shopify order creation payload
 */
export interface ShopifyOrderPayload {
  order: {
    email: string;
    financial_status: FinancialStatus;
    fulfillment_status: FulfillmentStatus;
    send_receipt: false;
    send_fulfillment_receipt: false;
    line_items: ShopifyLineItem[];
    shipping_address: ShopifyAddress;
    billing_address?: ShopifyAddress;
    created_at?: string;
    tags: string;
    note?: string;
  };
}

/**
 * Shopify order response from API
 */
export interface ShopifyOrderResponse {
  order: {
    id: number;
    admin_graphql_api_id: string;
    email: string;
    financial_status: string;
    fulfillment_status: string | null;
    created_at: string;
    updated_at: string;
    name: string;
    order_number: number;
    tags: string;
  };
}

/**
 * Shopify orders list response
 */
export interface ShopifyOrdersListResponse {
  orders: ShopifyOrderResponse["order"][];
}

/**
 * Shopify order count response
 */
export interface ShopifyOrderCountResponse {
  count: number;
}

/**
 * Shopify error response
 */
export interface ShopifyErrorResponse {
  errors: string | Record<string, string[]>;
}

// =============================================================================
// Address Database Types
// =============================================================================

/**
 * US state code
 */
export type USStateCode =
  | "CA"
  | "NY"
  | "TX"
  | "FL"
  | "IL"
  | "PA"
  | "OH"
  | "GA"
  | "NC"
  | "MI"
  | "NJ"
  | "VA"
  | "WA"
  | "AZ"
  | "MA"
  | "TN"
  | "IN"
  | "MO"
  | "MD"
  | "WI"
  | "CO"
  | "MN"
  | "SC"
  | "AL"
  | "LA"
  | "KY"
  | "OR"
  | "OK"
  | "CT"
  | "UT"
  | "NV"
  | "AR"
  | "MS"
  | "KS"
  | "NM"
  | "NE"
  | "ID"
  | "WV"
  | "HI"
  | "NH"
  | "ME"
  | "MT"
  | "RI"
  | "DE"
  | "SD"
  | "ND"
  | "AK"
  | "VT"
  | "DC"
  | "WY";

/**
 * Pre-validated US address
 */
export interface ValidatedAddress {
  address1: string;
  address2?: string;
  city: string;
  state: USStateCode;
  zip: string;
  /** Landmark name for easier identification */
  landmark?: string;
}

/**
 * State distribution configuration
 */
export interface StateDistribution {
  state: USStateCode;
  weight: number;
}

// =============================================================================
// Progress Tracking Types
// =============================================================================

/**
 * Error record for failed order creation
 */
export interface OrderError {
  index: number;
  message: string;
  timestamp: string;
}

/**
 * Progress tracker state persisted to disk
 */
export interface ProgressState {
  /** Version for state file format */
  version: 1;
  /** Unique session ID */
  sessionId: string;
  /** Target order count */
  targetCount: number;
  /** Successfully created order IDs */
  createdOrderIds: number[];
  /** Next index to create (for resume) */
  nextIndex: number;
  /** Errors encountered during generation */
  errors: OrderError[];
  /** Timestamp when generation started */
  startedAt: string;
  /** Timestamp of last update */
  updatedAt: string;
  /** Whether generation is complete */
  completed: boolean;
  /** Random seed used for reproducibility */
  seed: number;
}

// =============================================================================
// CLI Types
// =============================================================================

/**
 * Options for generate command
 */
export interface GenerateOptions {
  /** Number of orders to generate */
  count: number;
  /** Resume from previous interrupted run */
  resume: boolean;
  /** Preview without creating orders */
  dryRun: boolean;
  /** Concurrency level (1-10) */
  concurrency: number;
  /** Random seed for reproducibility */
  seed?: number;
}

/**
 * Options for cleanup command
 */
export interface CleanupOptions {
  /** Delete all test orders (not just from state file) */
  all: boolean;
  /** Skip confirmation prompt */
  force: boolean;
}

/**
 * Options for verify command
 */
export interface VerifyOptions {
  /** Show detailed distribution analysis */
  detailed: boolean;
}

/**
 * Order generation statistics
 */
export interface GenerationStats {
  totalOrders: number;
  successCount: number;
  errorCount: number;
  elapsedMs: number;
  ordersPerSecond: number;
  stateDistribution: Record<string, number>;
  statusDistribution: {
    unfulfilled: number;
    partial: number;
    fulfilled: number;
  };
  financialDistribution: {
    paid: number;
    pending: number;
    refunded: number;
  };
}

// =============================================================================
// Shopify Client Types
// =============================================================================

/**
 * Shopify client configuration
 */
export interface ShopifyClientConfig {
  /** Shopify store domain (e.g., my-store.myshopify.com) */
  storeDomain: string;
  /** Admin API access token */
  accessToken: string;
  /** API version (e.g., 2024-01) */
  apiVersion: string;
  /** Requests per second limit */
  rateLimit: number;
}

/**
 * Rate limiter state
 */
export interface RateLimiterState {
  tokens: number;
  lastRefill: number;
}
