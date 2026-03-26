/**
 * DataSourceMappersService
 *
 * Utility service that transforms raw schema columns from the backend API
 * into ColumnMetadata objects suitable for display in the UI.
 * Port of frontend/src/components/sidebar/dataSourceMappers.ts.
 */

import { Injectable } from '@angular/core';
import type { ColumnMetadata } from '@shipagent/shared-types';

interface SourceColumn {
  name: string;
  type: string;
  nullable: boolean;
}

@Injectable({ providedIn: 'root' })
export class DataSourceMappersService {
  /**
   * Maps raw backend schema columns to ColumnMetadata for display.
   * Preserves type, nullability, and initialises warnings as empty array.
   */
  mapSchemaColumns(columns: SourceColumn[]): ColumnMetadata[] {
    return columns.map((col) => ({
      name: col.name,
      type: col.type as ColumnMetadata['type'],
      nullable: col.nullable,
      warnings: [],
    }));
  }

  /**
   * Extracts a display filename from a data source path.
   * Returns null when no path is set on the source.
   */
  extractFileName(csvPath?: string, excelPath?: string, filePath?: string): string | null {
    const path = csvPath ?? excelPath ?? filePath;
    if (!path) return null;
    const segments = path.split('/');
    return segments[segments.length - 1] ?? null;
  }
}
