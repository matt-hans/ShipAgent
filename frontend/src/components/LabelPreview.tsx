/**
 * LabelPreview component for in-browser PDF label viewing.
 *
 * Renders shipping labels in a modal dialog with react-pdf,
 * allowing users to preview before downloading.
 */

import * as React from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

// Configure PDF.js worker - resolves the local pdfjs-dist worker file via Vite.
// IMPORTANT: pdfjs-dist in package.json must be pinned to the exact version that
// react-pdf depends on (check react-pdf's package.json). A version mismatch causes
// "API version X does not match Worker version Y" errors at runtime.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString();

export interface LabelPreviewProps {
  /** The UPS tracking number for the label (used for single-label view). */
  trackingNumber?: string;
  /** Direct PDF URL (used for merged labels or custom sources). */
  pdfUrl?: string;
  /** Title displayed in the modal header. */
  title?: string;
  /** Whether the modal is open. */
  isOpen: boolean;
  /** Callback when modal closes. */
  onClose: () => void;
}

/** Loading state component. */
function LoadingState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <LoadingIcon className="h-8 w-8 animate-spin mb-4" />
      <p>Loading label...</p>
    </div>
  );
}

/** Error state component. */
function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-red-600 dark:text-red-400">
      <AlertIcon className="h-8 w-8 mb-4" />
      <p className="text-sm font-medium mb-2">Failed to load label</p>
      <p className="text-xs text-muted-foreground">{message}</p>
    </div>
  );
}

/**
 * LabelPreview displays a PDF shipping label in a modal dialog.
 *
 * Features:
 * - Modal dialog with react-pdf Document and Page components
 * - Loading state while PDF loads
 * - Error state if PDF fails to load
 * - Download button in modal footer
 * - Close on backdrop click or Escape key (via Radix Dialog)
 * - Fits label to modal width
 */
export function LabelPreview({
  trackingNumber,
  pdfUrl: pdfUrlProp,
  title,
  isOpen,
  onClose,
}: LabelPreviewProps) {
  const [numPages, setNumPages] = React.useState<number>(0);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [containerWidth, setContainerWidth] = React.useState<number>(500);
  const containerRef = React.useRef<HTMLDivElement>(null);

  // Resolve PDF URL: explicit pdfUrl prop takes priority over trackingNumber
  const resolvedPdfUrl = pdfUrlProp || (trackingNumber ? `/api/v1/labels/${trackingNumber}` : '');

  // Observe container width for responsive PDF scaling
  React.useEffect(() => {
    if (!containerRef.current) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        // Account for padding (24px on each side)
        setContainerWidth(entry.contentRect.width);
      }
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Reset state when modal opens
  React.useEffect(() => {
    if (isOpen) {
      setIsLoading(true);
      setError(null);
      setNumPages(0);
    }
  }, [isOpen, trackingNumber, pdfUrlProp]);

  const handleLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setIsLoading(false);
    setError(null);
  };

  const handleLoadError = (err: Error) => {
    setIsLoading(false);
    setError(err.message || 'Could not load PDF');
  };

  const handleDownload = () => {
    const link = document.createElement('a');
    link.href = resolvedPdfUrl;
    link.download = trackingNumber ? `${trackingNumber}.pdf` : 'labels.pdf';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handlePrint = () => {
    const printWindow = window.open(resolvedPdfUrl, '_blank');
    if (printWindow) {
      printWindow.addEventListener('load', () => {
        printWindow.print();
      });
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] flex flex-col">
        {/* Visually hidden header for accessibility */}
        <DialogHeader className="sr-only">
          <DialogTitle>Label Preview</DialogTitle>
          <DialogDescription>Shipping label preview</DialogDescription>
        </DialogHeader>

        <div
          ref={containerRef}
          className="flex-1 overflow-y-auto min-h-0 bg-muted/30 rounded-md p-4"
        >
          {isLoading && !error && <LoadingState />}
          {error && <ErrorState message={error} />}

          <Document
            file={resolvedPdfUrl}
            onLoadSuccess={handleLoadSuccess}
            onLoadError={handleLoadError}
            loading={<LoadingState />}
            error={<ErrorState message="Failed to load PDF document" />}
            className={cn('flex flex-col items-center gap-4', isLoading && 'hidden')}
          >
            {Array.from(new Array(numPages), (_, index) => (
              <Page
                key={`page_${index + 1}`}
                pageNumber={index + 1}
                width={containerWidth - 32} // Subtract padding
                renderTextLayer={false}
                renderAnnotationLayer={false}
                className="shadow-md"
              />
            ))}
          </Document>
        </div>

        <DialogFooter className="border-t pt-4 gap-2 sm:gap-0">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button variant="outline" onClick={handlePrint} disabled={isLoading || !!error}>
            <PrinterIcon className="h-4 w-4 mr-2" />
            Print
          </Button>
          <Button onClick={handleDownload} disabled={isLoading || !!error}>
            <DownloadIcon className="h-4 w-4 mr-2" />
            Download
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Inline SVG icons to avoid external dependencies
function LoadingIcon({ className }: { className?: string }) {
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
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}

function AlertIcon({ className }: { className?: string }) {
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
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

function PrinterIcon({ className }: { className?: string }) {
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
      <polyline points="6 9 6 2 18 2 18 9" />
      <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
      <rect x="6" y="14" width="12" height="8" />
    </svg>
  );
}

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

export default LabelPreview;
