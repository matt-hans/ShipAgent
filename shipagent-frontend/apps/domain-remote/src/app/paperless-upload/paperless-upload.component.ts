/**
 * PaperlessUploadComponent
 *
 * Port of React PaperlessUploadCard.tsx.
 * Agent-initiated upload card for paperless customs documents.
 * Provides file picker, document type dropdown, notes, and upload action.
 * Domain color: paperless/amber via card-domain-paperless CSS class.
 */

import {
  Component,
  Input,
  OnInit,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  signal,
  inject,
  ViewChild,
  ElementRef,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  FileIconComponent,
  XIconComponent,
  UploadIconComponent,
} from '@shipagent/shared-ui';
import { ApiService } from '@shipagent/shared-api';
import type { PaperlessUploadPrompt } from '@shipagent/shared-types';
import { firstValueFrom } from 'rxjs';

type UploadState = 'empty' | 'selected' | 'uploading' | 'completed' | 'error';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

@Component({
  selector: 'app-paperless-upload',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, FileIconComponent, XIconComponent, UploadIconComponent],
  providers: [],
  template: `
    <div class="card-premium p-4 space-y-3 border-l-4 card-domain-paperless">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <sa-icon-upload class="w-4 h-4 text-[var(--color-domain-paperless)]" />
          <h4 class="text-sm font-medium text-foreground">Upload Customs Document</h4>
        </div>
        @if (uploadState() === 'completed') {
          <span class="badge badge-success text-xs">Uploaded</span>
        }
      </div>

      <!-- Prompt -->
      <p class="text-xs text-muted-foreground">{{ data.prompt }}</p>

      <!-- Content (hidden after completion) -->
      @if (uploadState() !== 'completed') {
        <!-- Drop zone / file preview -->
        @if (!selectedFile()) {
          <div
            role="button"
            tabindex="0"
            class="border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors"
            [class.border-border]="!isDragOver()"
            [class.hover:border-muted-foreground/40]="!isDragOver()"
            [class.border-amber-400]="isDragOver()"
            [class.bg-amber-400/5]="isDragOver()"
            [class.opacity-50]="isLocked()"
            [class.pointer-events-none]="isLocked()"
            (click)="fileInput.click()"
            (keydown)="onDropZoneKeydown($event)"
            (dragover)="onDragOver($event)"
            (dragleave)="onDragLeave($event)"
            (drop)="onDrop($event)"
          >
            <sa-icon-file class="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
            <p class="text-xs text-muted-foreground">Drag &amp; drop your file here or click to browse</p>
            <p class="text-[10px] text-muted-foreground/70 mt-1">
              {{ acceptedFormatsDisplay }} · Max 10 MB
            </p>
          </div>
        } @else {
          <!-- File selected preview -->
          <div class="flex items-center gap-2 px-3 py-2 rounded-md bg-muted">
            <sa-icon-file class="w-4 h-4 text-[var(--color-domain-paperless)] shrink-0" />
            <div class="flex-1 min-w-0">
              <p class="text-xs font-medium text-foreground truncate">{{ selectedFile()!.name }}</p>
              <p class="text-[10px] text-muted-foreground">{{ formatSize(selectedFile()!.size) }}</p>
            </div>
            @if (!isLocked()) {
              <button
                (click)="removeFile()"
                class="p-0.5 hover:bg-background rounded"
                aria-label="Remove file"
              >
                <sa-icon-x class="w-3.5 h-3.5 text-muted-foreground" />
              </button>
            }
          </div>
        }

        <!-- Document type dropdown -->
        <div class="flex items-center gap-3">
          <label for="doc-type-select" class="text-xs text-muted-foreground whitespace-nowrap">
            Document Type
          </label>
          <select
            id="doc-type-select"
            [(ngModel)]="documentType"
            [disabled]="isLocked()"
            class="flex-1 text-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground disabled:opacity-50"
          >
            @for (dt of data.document_types; track dt.code) {
              <option [value]="dt.code">{{ dt.label }}</option>
            }
          </select>
        </div>

        <!-- Notes -->
        <div class="flex items-start gap-3">
          <label for="doc-notes" class="text-xs text-muted-foreground whitespace-nowrap pt-1.5">
            Notes
          </label>
          <input
            id="doc-notes"
            type="text"
            [(ngModel)]="notes"
            [disabled]="isLocked()"
            placeholder="Optional notes..."
            class="flex-1 text-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground placeholder:text-muted-foreground/50 disabled:opacity-50"
          />
        </div>

        <!-- Error message -->
        @if (errorMessage()) {
          <p class="text-xs text-red-500">{{ errorMessage() }}</p>
        }

        <!-- Action buttons -->
        <div class="flex justify-end gap-2 pt-1">
          <button
            (click)="cancelled.emit()"
            [disabled]="isLocked()"
            class="btn-secondary text-xs px-3 py-1.5"
          >
            Cancel
          </button>
          <button
            (click)="handleSubmit()"
            [disabled]="!selectedFile() || isLocked()"
            class="btn-primary text-xs px-3 py-1.5 disabled:opacity-50"
          >
            {{ uploadState() === 'uploading' ? 'Uploading...' : 'Upload' }}
          </button>
        </div>
      }

      <!-- Hidden file input -->
      <input
        #fileInput
        type="file"
        [accept]="acceptAttr"
        (change)="onFileChange($event)"
        class="hidden"
      />
    </div>
  `,
})
export class PaperlessUploadComponent implements OnInit {
  @Input({ required: true }) data!: PaperlessUploadPrompt;
  @Input() sessionId = '';
  @Output() uploadComplete = new EventEmitter<void>();
  @Output() cancelled = new EventEmitter<void>();
  @Input() disabled = false;

  @ViewChild('fileInput') fileInputRef!: ElementRef<HTMLInputElement>;

  private readonly apiService = inject(ApiService);

  readonly selectedFile = signal<File | null>(null);
  readonly uploadState = signal<UploadState>('empty');
  readonly errorMessage = signal('');
  readonly isDragOver = signal(false);

  documentType = '';
  notes = '';

  get acceptAttr(): string {
    return (this.data?.accepted_formats ?? []).map((f) => `.${f}`).join(',');
  }

  get acceptedFormatsDisplay(): string {
    return (this.data?.accepted_formats ?? []).map((f) => f.toUpperCase()).join(', ');
  }

  isLocked(): boolean {
    return this.disabled || this.uploadState() === 'uploading' || this.uploadState() === 'completed';
  }

  protected formatSize = formatFileSize;

  ngOnInit(): void {
    this.documentType =
      this.data?.suggested_document_type ||
      this.data?.document_types?.[0]?.code ||
      '002';
  }

  private validateFile(file: File): string | null {
    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    const formats = this.data?.accepted_formats ?? [];
    if (formats.length > 0 && !formats.includes(ext)) {
      return `Unsupported format "${ext}". Allowed: ${formats.join(', ')}`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File exceeds 10 MB limit (${formatFileSize(file.size)}).`;
    }
    return null;
  }

  private handleFileSelected(file: File): void {
    const validationError = this.validateFile(file);
    if (validationError) {
      this.errorMessage.set(validationError);
      this.uploadState.set('error');
      return;
    }
    this.selectedFile.set(file);
    this.errorMessage.set('');
    this.uploadState.set('selected');
  }

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) this.handleFileSelected(file);
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(false);
    const file = event.dataTransfer?.files[0];
    if (file) this.handleFileSelected(file);
  }

  onDropZoneKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ' ') {
      this.fileInputRef?.nativeElement?.click();
    }
  }

  removeFile(): void {
    this.selectedFile.set(null);
    this.uploadState.set('empty');
    this.errorMessage.set('');
    if (this.fileInputRef?.nativeElement) {
      this.fileInputRef.nativeElement.value = '';
    }
  }

  async handleSubmit(): Promise<void> {
    const file = this.selectedFile();
    if (!file) return;
    this.uploadState.set('uploading');
    this.errorMessage.set('');
    try {
      await firstValueFrom(
        this.apiService.uploadDocument(
          this.sessionId,
          file,
          this.documentType,
          this.notes || undefined,
        ),
      );
      this.uploadState.set('completed');
      this.uploadComplete.emit();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload failed';
      this.errorMessage.set(msg);
      this.uploadState.set('error');
    }
  }
}
