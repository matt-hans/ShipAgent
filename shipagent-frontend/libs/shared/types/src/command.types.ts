/**
 * Custom slash command types.
 */

/** User-defined slash command that expands to a shipping instruction. */
export interface CustomCommand {
  id: string;
  name: string;
  description: string | null;
  body: string;
  created_at: string;
  updated_at: string;
}

/** Command creation request payload. */
export interface CommandCreate {
  name: string;
  description?: string;
  body: string;
}

/** Command update request payload. */
export interface CommandUpdate {
  name?: string;
  description?: string;
  body?: string;
}

/** Paginated command list response. */
export interface CommandListResponse {
  commands: CustomCommand[];
  total: number;
}
