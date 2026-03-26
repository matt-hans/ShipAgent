/**
 * External platform connection types.
 */

/** Supported external platform identifiers. */
export type PlatformType = 'shopify' | 'amazon' | 'woocommerce' | 'sap' | 'oracle';

/** Platform connection status values. */
export type ConnectionStatus = 'connected' | 'disconnected' | 'error' | 'authenticating';

/** Platform connection state. */
export interface PlatformConnection {
  platform: PlatformType;
  store_url: string | null;
  status: ConnectionStatus;
  last_connected: string | null;
  error_message: string | null;
}

/** List connections response. */
export interface ListConnectionsResponse {
  connections: PlatformConnection[];
  count: number;
}

/** Connect platform request - Shopify. */
export interface ShopifyCredentials {
  access_token: string;
}

/** Connect platform request - WooCommerce. */
export interface WooCommerceCredentials {
  consumer_key: string;
  consumer_secret: string;
}

/** Connect platform request - SAP. */
export interface SAPCredentials {
  base_url: string;
  username: string;
  password: string;
  client: string;
}

/** Connect platform request - Oracle (individual params). */
export interface OracleCredentialsParams {
  host: string;
  port?: number;
  service_name: string;
  user: string;
  password: string;
}

/** Connect platform request - Oracle (connection string). */
export interface OracleCredentialsString {
  connection_string: string;
}

/** Union type for Oracle credentials. */
export type OracleCredentials = OracleCredentialsParams | OracleCredentialsString;

/** Connect platform request - Amazon SP-API. */
export interface AmazonCredentials {
  client_id: string;
  client_secret: string;
  refresh_token: string;
  marketplace_id?: string;
  sandbox?: boolean;
}

/** All credential types union. */
export type PlatformCredentials =
  | { platform: 'shopify'; credentials: ShopifyCredentials; store_url: string }
  | { platform: 'amazon'; credentials: AmazonCredentials; store_url?: string }
  | { platform: 'woocommerce'; credentials: WooCommerceCredentials; store_url: string }
  | { platform: 'sap'; credentials: SAPCredentials; store_url?: string }
  | { platform: 'oracle'; credentials: OracleCredentials; store_url?: string };

/** Connect platform response. */
export interface ConnectPlatformResponse {
  success: boolean;
  platform: PlatformType;
  status: string;
  message?: string;
  error?: string;
}

/** Order filters for fetching from external platforms. */
export interface OrderFilters {
  status?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

/** Line item in an external order. */
export interface ExternalOrderItem {
  id: string;
  name: string;
  quantity: number;
  total: string;
  sku: string;
}

/** Order from external platform (normalized). */
export interface ExternalOrder {
  platform: PlatformType;
  order_id: string;
  order_number: string | null;
  status: string;
  created_at: string;
  customer_name: string;
  customer_email: string | null;
  ship_to_name: string;
  ship_to_company: string | null;
  ship_to_address1: string;
  ship_to_address2: string | null;
  ship_to_city: string;
  ship_to_state: string;
  ship_to_postal_code: string;
  ship_to_country: string;
  ship_to_phone: string | null;
  items: ExternalOrderItem[];
}

/** List orders response. */
export interface ListOrdersResponse {
  success: boolean;
  platform: PlatformType;
  orders: ExternalOrder[];
  count: number;
  total?: number;
  error?: string;
}

/** Get single order response. */
export interface GetOrderResponse {
  success: boolean;
  platform: PlatformType;
  order?: ExternalOrder;
  error?: string;
}

/** Tracking update request. */
export interface TrackingUpdateRequest {
  platform: PlatformType;
  order_id: string;
  tracking_number: string;
  carrier?: string;
}

/** Tracking update response. */
export interface TrackingUpdateResponse {
  success: boolean;
  platform: PlatformType;
  order_id: string;
  tracking_number?: string;
  carrier?: string;
  error?: string;
}

/** Shopify environment status response. */
export interface ShopifyEnvStatus {
  /** True if both SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN are set. */
  configured: boolean;
  /** True if credentials validated against Shopify API. */
  valid: boolean;
  /** Store URL from environment. */
  store_url: string | null;
  /** Shop name from Shopify API. */
  store_name: string | null;
  /** Error message if validation failed. */
  error: string | null;
}

/** Amazon environment status response. */
export interface AmazonEnvStatus {
  /** True if Amazon SP-API credentials are configured. */
  configured: boolean;
  /** True if credentials validated against Amazon API. */
  valid: boolean;
  /** Amazon marketplace ID. */
  marketplace_id: string | null;
  /** Seller/marketplace name from Amazon. */
  seller_name: string | null;
  /** Error message if validation failed. */
  error: string | null;
}
