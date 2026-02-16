/**
 * Inline card for paperless document operation results in the chat thread.
 *
 * Renders uploaded/pushed/deleted status with amber domain border.
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

export function PaperlessCard({ data }: { data: PaperlessResult }) {
  const meta = ACTION_META[data.action] ?? ACTION_META.uploaded;

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

      {data.documentId && (
        <div className="flex items-center gap-2 text-xs font-mono px-2 py-1.5 rounded bg-muted">
          <span className="text-muted-foreground">Document ID:</span>
          <span className="text-foreground">{data.documentId}</span>
        </div>
      )}
    </div>
  );
}
