/**
 * Domain card result types from UPS MCP v2 SSE events.
 * These are emitted by the agent and displayed as rich domain cards in the UI.
 */

/** Pickup operation result from SSE stream. */
export interface PickupResult {
  action: 'scheduled' | 'cancelled' | 'rated' | 'status';
  success: boolean;
  prn?: string;
  // Enriched completion fields (present when action === 'scheduled')
  address_line?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country_code?: string;
  pickup_date?: string;
  ready_time?: string;
  close_time?: string;
  contact_name?: string;
  phone_number?: string;
  grand_total?: string;
  charges?: Array<{ chargeAmount: string; chargeCode: string; chargeLabel: string }>;
  pickups?: Array<{ pickupDate: string; prn: string }>;
}

/** Location search result from SSE stream. */
export interface LocationResult {
  action: 'locations' | 'service_centers';
  success: boolean;
  locations?: Array<{
    id: string;
    address: Record<string, string>;
    phone?: string;
    phones?: string[];
    hours?: Record<string, string>;
    details?: Record<string, unknown>;
  }>;
  facilities?: Array<{
    name: string;
    address: string;
    phone?: string;
    phones?: string[];
    timezone?: string;
    slic?: string;
    type?: string;
    hours?: Record<string, string>;
    details?: Record<string, unknown>;
  }>;
}

/** Landed cost estimation result from SSE stream. */
export interface LandedCostResult {
  action: 'landed_cost';
  success: boolean;
  totalLandedCost: string;
  currencyCode: string;
  shipmentId?: string;
  transId?: string;
  alVersion?: number;
  perfStats?: {
    absLayerTime?: string;
    fulfillTime?: string;
    receiptTime?: string;
  };
  importCountryCode?: string;
  totalDuties?: string;
  totalVAT?: string;
  totalCommodityLevelTaxesAndFees?: string;
  totalShipmentLevelTaxesAndFees?: string;
  totalDutyAndTax?: string;
  totalBrokerageFees?: string;
  brokerageFeeItems?: Array<{
    chargeName: string;
    chargeAmount: string;
  }>;
  requestSummary?: {
    exportCountryCode: string;
    importCountryCode: string;
    currencyCode: string;
    shipmentType: string;
    commodityCount: number;
    totalUnits: number;
    declaredMerchandiseValue: string;
  };
  items: Array<{
    commodityId: string;
    itemLabel?: string;
    duties: string;
    taxes: string;
    fees: string;
    totalDutyAndTax?: string;
    currencyCode?: string;
    isCalculable?: boolean;
    hsCode?: string;
  }>;
}

/** Upload prompt event data emitted by request_document_upload tool. */
export interface PaperlessUploadPrompt {
  accepted_formats: string[];
  document_types: { code: string; label: string }[];
  prompt: string;
  suggested_document_type?: string;
}

/** Paperless document operation result from SSE stream. */
export interface PaperlessResult {
  action: 'uploaded' | 'pushed' | 'deleted';
  success: boolean;
  documentId?: string;
  documentIds?: string[];
  formsGroupId?: string;
  statusCode?: string;
  statusDescription?: string;
  customerContext?: string;
  alerts?: Array<{
    code?: string;
    message?: string;
  }>;
  fileName?: string;
  fileFormat?: string;
  documentType?: string;
  fileSizeBytes?: number;
}

/** Package tracking result from SSE stream. */
export interface TrackingResult {
  action: 'tracked';
  success: boolean;
  trackingNumber: string;
  mismatch?: boolean;
  requestedNumber?: string;
  currentStatus?: string;
  statusDescription?: string;
  deliveryDate?: string;
  activities?: Array<{
    date: string;
    time: string;
    location: string;
    status: string;
  }>;
}

/** Pickup preview data emitted before scheduling for user confirmation. */
export interface PickupPreview {
  address_line: string;
  city: string;
  state: string;
  postal_code: string;
  country_code: string;
  pickup_date: string;
  ready_time: string;
  close_time: string;
  pickup_type: string;
  contact_name: string;
  phone_number: string;
  charges: Array<{ chargeCode: string; chargeLabel: string; chargeAmount: string }>;
  grand_total: string;
  confirmation_token?: string;
}

/** Agent-driven contact save result from SSE stream. */
export interface ContactSavedResult {
  action: 'created' | 'updated';
  handle: string;
  display_name: string;
  attention_name: string | null;
  company: string | null;
  phone: string | null;
  email: string | null;
  address_line_1: string;
  address_line_2: string | null;
  city: string;
  state_province: string | null;
  postal_code: string;
  country_code: string;
  tags: string[];
}
