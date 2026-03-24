/**
 * Address book contact types.
 */

/** Contact in the address book for @handle resolution. */
export interface Contact {
  id: string;
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
  use_as_ship_to: boolean;
  use_as_shipper: boolean;
  use_as_third_party: boolean;
  tags: string[];
  notes: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

/** Contact creation request payload. */
export interface ContactCreate {
  handle?: string;
  display_name: string;
  attention_name?: string;
  company?: string;
  phone?: string;
  email?: string;
  address_line_1: string;
  address_line_2?: string;
  city: string;
  state_province?: string;
  postal_code: string;
  country_code?: string;
  use_as_ship_to?: boolean;
  use_as_shipper?: boolean;
  use_as_third_party?: boolean;
  tags?: string[];
  notes?: string;
}

/** Contact update request payload. */
export interface ContactUpdate {
  handle?: string;
  display_name?: string;
  attention_name?: string;
  company?: string;
  phone?: string;
  email?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state_province?: string;
  postal_code?: string;
  country_code?: string;
  use_as_ship_to?: boolean;
  use_as_shipper?: boolean;
  use_as_third_party?: boolean;
  tags?: string[];
  notes?: string;
}

/** Paginated contact list response. */
export interface ContactListResponse {
  contacts: Contact[];
  total: number;
}
