import type { ColumnMetadata } from '@/types/api';

interface SourceColumn {
  name: string;
  type: string;
  nullable: boolean;
}

export function toDataSourceColumns(columns: SourceColumn[]): ColumnMetadata[] {
  return columns.map((column) => ({
    name: column.name,
    type: column.type as ColumnMetadata['type'],
    nullable: column.nullable,
    warnings: [],
  }));
}
