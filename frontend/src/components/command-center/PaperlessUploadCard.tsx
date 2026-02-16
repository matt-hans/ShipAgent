/**
 * Agent-initiated upload card for paperless customs documents.
 *
 * Rendered in the chat thread when the agent calls `request_document_upload`.
 * Provides drag-and-drop / click-to-browse file picker, document type
 * dropdown, optional notes, and submit/cancel buttons.
 *
 * Design matches existing domain card patterns (amber border for paperless).
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import { uploadDocument } from '@/lib/api';
import type { PaperlessUploadPrompt } from '@/types/api';
import { FileIcon, XIcon, UploadIcon } from '@/components/ui/icons';

type UploadState = 'empty' | 'selected' | 'uploading' | 'completed' | 'error';

interface PaperlessUploadCardProps {
  data: PaperlessUploadPrompt;
  sessionId: string;
  onUploadComplete: () => void;
  onCancel: () => void;
  disabled?: boolean;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

export function PaperlessUploadCard({
  data,
  sessionId,
  onUploadComplete,
  onCancel,
  disabled,
}: PaperlessUploadCardProps) {
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [file, setFile] = React.useState<File | null>(null);
  const [documentType, setDocumentType] = React.useState(
    data.suggested_document_type || data.document_types[0]?.code || '002',
  );
  const [notes, setNotes] = React.useState('');
  const [state, setState] = React.useState<UploadState>('empty');
  const [error, setError] = React.useState('');
  const [isDragOver, setIsDragOver] = React.useState(false);

  const acceptAttr = data.accepted_formats
    .map((f) => `.${f}`)
    .join(',');

  function validateFile(f: File): string | null {
    const ext = f.name.split('.').pop()?.toLowerCase() || '';
    if (!data.accepted_formats.includes(ext)) {
      return `Unsupported format "${ext}". Allowed: ${data.accepted_formats.join(', ')}`;
    }
    if (f.size > MAX_FILE_SIZE) {
      return `File exceeds 10 MB limit (${formatFileSize(f.size)}).`;
    }
    return null;
  }

  function handleFileSelected(selectedFile: File) {
    const validationError = validateFile(selectedFile);
    if (validationError) {
      setError(validationError);
      setState('error');
      return;
    }
    setFile(selectedFile);
    setError('');
    setState('selected');
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) handleFileSelected(f);
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFileSelected(f);
  }

  function handleRemoveFile() {
    setFile(null);
    setState('empty');
    setError('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  async function handleSubmit() {
    if (!file) return;
    setState('uploading');
    setError('');
    try {
      await uploadDocument(sessionId, file, documentType, notes || undefined);
      setState('completed');
      onUploadComplete();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload failed';
      setError(msg);
      setState('error');
    }
  }

  const isLocked = disabled || state === 'uploading' || state === 'completed';

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-paperless')}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <UploadIcon className="w-4 h-4 text-[var(--color-domain-paperless)]" />
          <h4 className="text-sm font-medium text-foreground">Upload Customs Document</h4>
        </div>
        {state === 'completed' && (
          <span className="badge badge-success text-xs">Uploaded</span>
        )}
      </div>

      {/* Prompt */}
      <p className="text-xs text-muted-foreground">{data.prompt}</p>

      {/* Drop zone / file preview */}
      {state !== 'completed' && (
        <>
          {!file ? (
            <div
              role="button"
              tabIndex={0}
              className={cn(
                'border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors',
                isDragOver
                  ? 'border-[var(--color-domain-paperless)] bg-[var(--color-domain-paperless)]/5'
                  : 'border-border hover:border-muted-foreground/40',
                isLocked && 'opacity-50 pointer-events-none',
              )}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <FileIcon className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
              <p className="text-xs text-muted-foreground">
                Drag & drop your file here or click to browse
              </p>
              <p className="text-[10px] text-muted-foreground/70 mt-1">
                {data.accepted_formats.map((f) => f.toUpperCase()).join(', ')} · Max 10 MB
              </p>
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-muted">
              <FileIcon className="w-4 h-4 text-[var(--color-domain-paperless)] shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-foreground truncate">{file.name}</p>
                <p className="text-[10px] text-muted-foreground">{formatFileSize(file.size)}</p>
              </div>
              {!isLocked && (
                <button
                  onClick={handleRemoveFile}
                  className="p-0.5 hover:bg-background rounded"
                  aria-label="Remove file"
                >
                  <XIcon className="w-3.5 h-3.5 text-muted-foreground" />
                </button>
              )}
            </div>
          )}

          {/* Document type dropdown */}
          <div className="flex items-center gap-3">
            <label htmlFor="doc-type-select" className="text-xs text-muted-foreground whitespace-nowrap">
              Document Type
            </label>
            <select
              id="doc-type-select"
              value={documentType}
              onChange={(e) => setDocumentType(e.target.value)}
              disabled={isLocked}
              className="flex-1 text-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground disabled:opacity-50"
            >
              {data.document_types.map((dt) => (
                <option key={dt.code} value={dt.code}>
                  {dt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Notes */}
          <div className="flex items-start gap-3">
            <label htmlFor="doc-notes" className="text-xs text-muted-foreground whitespace-nowrap pt-1.5">
              Notes
            </label>
            <input
              id="doc-notes"
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={isLocked}
              placeholder="Optional notes..."
              className="flex-1 text-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground placeholder:text-muted-foreground/50 disabled:opacity-50"
            />
          </div>

          {/* Error message */}
          {error && (
            <p className="text-xs text-red-500">{error}</p>
          )}

          {/* Action buttons */}
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onCancel}
              disabled={isLocked}
              className="btn-secondary text-xs px-3 py-1.5"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!file || isLocked}
              className="btn-primary text-xs px-3 py-1.5 disabled:opacity-50"
            >
              {state === 'uploading' ? 'Uploading...' : 'Upload'}
            </button>
          </div>
        </>
      )}

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept={acceptAttr}
        onChange={handleInputChange}
        className="hidden"
      />
    </div>
  );
}
