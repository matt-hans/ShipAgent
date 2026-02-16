/**
 * Inline card for paperless document operation results in the chat thread.
 *
 * Renders uploaded/pushed/deleted status with amber domain border.
 * Enhanced: shows file metadata (name, type, format, size) when present.
 * Accepts PaperlessResult as props.
 */

import { cn } from '@/lib/utils';
import type { PaperlessResult } from '@/types/api';
import { CheckIcon, FileIcon } from '@/components/ui/icons';

const ACTION_META: Record<PaperlessResult['action'], { label: string; description: string }> = {
  uploaded: { label: 'Document Uploaded', description: 'Document uploaded to UPS Forms History.' },
  pushed: { label: 'Document Attached', description: 'Document attached to shipment.' },
  deleted: { label: 'Document Deleted', description: 'Document removed from Forms History.' },
};

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  '002': 'Commercial Invoice',
  '003': 'Certificate of Origin',
  '004': 'NAFTA Certificate',
  '005': 'Partial Invoice',
  '006': 'Packing List',
  '007': 'Customer Generated Forms',
  '008': 'Air Freight Invoice',
  '009': 'Proforma Invoice',
  '010': 'SED',
  '011': 'Weight Certificate',
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function PaperlessCard({ data }: { data: PaperlessResult }) {
  const meta = ACTION_META[data.action] ?? ACTION_META.uploaded;
  const hasFileInfo = data.fileName || data.fileFormat || data.documentType;
  const docTypeLabel = data.documentType ? DOCUMENT_TYPE_LABELS[data.documentType] || data.documentType : null;

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-paperless')}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileIcon className="w-4 h-4 text-[var(--color-domain-paperless)]" />
          <h4 className="text-sm font-medium text-foreground">{meta.label}</h4>
        </div>
        <span className="badge badge-success">
          <CheckIcon className="w-3 h-3 mr-1" />
          Done
        </span>
      </div>

      <p className="text-xs text-muted-foreground">{meta.description}</p>

      {/* File metadata block (enhanced — shown when upload card flow was used) */}
      {hasFileInfo && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-muted">
          <FileIcon className="w-4 h-4 text-[var(--color-domain-paperless)] shrink-0" />
          <div className="flex-1 min-w-0">
            {data.fileName && (
              <p className="text-xs font-medium text-foreground truncate">{data.fileName}</p>
            )}
            <p className="text-[10px] text-muted-foreground">
              {[
                docTypeLabel,
                data.fileFormat?.toUpperCase(),
                data.fileSizeBytes != null ? formatFileSize(data.fileSizeBytes) : null,
              ].filter(Boolean).join(' · ')}
            </p>
          </div>
        </div>
      )}

      {data.documentId && (
        <div className="flex items-center gap-2 text-xs font-mono px-2 py-1.5 rounded bg-muted">
          <span className="text-muted-foreground">Document ID:</span>
          <span className="text-foreground">{data.documentId}</span>
        </div>
      )}
    </div>
  );
}
