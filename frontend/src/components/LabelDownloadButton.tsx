/**
 * LabelDownloadButton component for downloading individual shipping labels.
 *
 * Provides icon or text variants for use in tables and detail views.
 */

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface LabelDownloadButtonProps {
  /** The UPS tracking number for the label. */
  trackingNumber: string;
  /** Job ID for per-row label access (handles non-unique tracking numbers). */
  jobId?: string;
  /** Row number within the job for per-row label access. */
  rowNumber?: number;
  /** Button variant: 'icon' for compact tables, 'text' for detail views. */
  variant?: 'icon' | 'text';
  /** Optional callback to open preview modal instead of direct download. */
  onPreview?: () => void;
  /** Whether to show preview option on click. */
  showPreviewOnClick?: boolean;
  /** Optional additional class name. */
  className?: string;
}

/**
 * LabelDownloadButton provides per-row label download functionality.
 *
 * Features:
 * - Icon variant: Compact download icon button for table rows
 * - Text variant: Full "Download Label" button for detail views
 * - Direct download via anchor with download attribute
 * - Optional preview callback with Shift+click
 */
export function LabelDownloadButton({
  trackingNumber,
  jobId,
  rowNumber,
  variant = 'icon',
  onPreview,
  showPreviewOnClick = false,
  className,
}: LabelDownloadButtonProps) {
  // Prefer per-row endpoint for unambiguous label access (handles
  // non-unique tracking numbers from UPS sandbox)
  const downloadUrl = jobId && rowNumber != null
    ? `/api/v1/jobs/${jobId}/labels/${rowNumber}`
    : `/api/v1/labels/${trackingNumber}`;
  const filename = `${trackingNumber}_row${rowNumber ?? 0}.pdf`;

  const handleClick = (e: React.MouseEvent) => {
    // If preview handler provided and showPreviewOnClick is true, open preview
    if (onPreview && showPreviewOnClick) {
      e.preventDefault();
      onPreview();
      return;
    }

    // If Shift is held and preview handler exists, open preview instead
    if (e.shiftKey && onPreview) {
      e.preventDefault();
      onPreview();
    }
    // Otherwise, let the anchor handle the download naturally
  };

  if (variant === 'icon') {
    return (
      <Button
        asChild
        variant="ghost"
        size="sm"
        className={cn('h-8 w-8 p-0', className)}
        title={`Download label for ${trackingNumber}`}
      >
        <a
          href={downloadUrl}
          download={filename}
          onClick={handleClick}
        >
          <DownloadIcon className="h-4 w-4" />
          <span className="sr-only">Download label</span>
        </a>
      </Button>
    );
  }

  return (
    <Button
      asChild
      variant="outline"
      size="sm"
      className={className}
    >
      <a
        href={downloadUrl}
        download={filename}
        onClick={handleClick}
      >
        <DownloadIcon className="h-4 w-4 mr-2" />
        Download Label
      </a>
    </Button>
  );
}

// Inline SVG icon
function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

export default LabelDownloadButton;
