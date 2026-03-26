/**
 * Data source and local file connection types.
 */

/** Supported data source types. */
export type DataSourceType = 'csv' | 'excel' | 'json' | 'xml' | 'fixed_width' | 'edi' | 'database';

/** Status of a data source import. */
export type DataSourceStatus = 'connected' | 'disconnected' | 'error';

/** Column data types from schema discovery. */
export type ColumnDataType =
  | 'INTEGER'
  | 'BIGINT'
  | 'VARCHAR'
  | 'TEXT'
  | 'BOOLEAN'
  | 'DATE'
  | 'TIMESTAMP'
  | 'DECIMAL'
  | 'DOUBLE'
  | 'UNKNOWN';

/** Column metadata from schema discovery. */
export interface ColumnMetadata {
  name: string;
  type: ColumnDataType;
  nullable: boolean;
  warnings: string[];
}

/** CSV import configuration. */
export interface CsvImportConfig {
  filePath: string;
  delimiter?: string;
  header?: boolean;
}

/** Excel import configuration. */
export interface ExcelImportConfig {
  filePath: string;
  sheet?: string;
  header?: boolean;
}

/** Database import configuration. */
export interface DatabaseImportConfig {
  connectionString: string;
  query: string;
  schema?: string;
}

/** Data source connection info. */
export interface DataSourceInfo {
  type: DataSourceType;
  status: DataSourceStatus;
  row_count?: number;
  column_count?: number;
  columns?: ColumnMetadata[];
  connected_at?: string;
  error?: string;
  // Type-specific details
  csv_path?: string;
  excel_path?: string;
  excel_sheet?: string;
  database_query?: string;
  /** Generic file path for json/xml/edi/fixed_width sources. */
  file_path?: string;
}

/** Sheet info for Excel files. */
export interface SheetInfo {
  name: string;
  index: number;
  row_count?: number;
}

/** Table info for databases. */
export interface TableInfo {
  name: string;
  row_count: number;
  requires_filter: boolean;
}

/** Request for importing a local data source. */
export interface DataSourceImportRequest {
  type: 'csv' | 'excel' | 'database';
  file_path?: string;
  delimiter?: string;
  sheet?: string;
  connection_string?: string;
  query?: string;
  row_key_columns?: string[];
}

/** Response from a data source import operation. */
export interface DataSourceImportResponse {
  status: 'connected' | 'error' | 'pending_agent_setup';
  source_type: string;
  row_count: number;
  columns: { name: string; type: string; nullable: boolean }[];
  error?: string;
  file_path?: string;
}

/** Status of the currently connected data source. */
export interface DataSourceStatusResponse {
  connected: boolean;
  source_type?: string;
  file_path?: string;
  row_count?: number;
  columns?: { name: string; type: string; nullable: boolean }[];
}

/** A previously connected data source persisted for reconnection. */
export interface SavedDataSource {
  id: string;
  name: string;
  source_type: DataSourceType;
  file_path: string | null;
  sheet_name: string | null;
  db_host: string | null;
  db_port: number | null;
  db_name: string | null;
  db_query: string | null;
  row_count: number;
  column_count: number;
  connected_at: string;
  last_used_at: string;
}

/** Response from listing saved data sources. */
export interface SavedDataSourceListResponse {
  sources: SavedDataSource[];
  total: number;
}

/** Request for reconnecting to a saved data source. */
export interface ReconnectRequest {
  source_id: string;
  connection_string?: string;
  row_key_columns?: string[];
}

/** Upload document response. */
export interface UploadDocumentResponse {
  success: boolean;
  file_name: string;
  file_format: string;
  file_size_bytes: number;
}
