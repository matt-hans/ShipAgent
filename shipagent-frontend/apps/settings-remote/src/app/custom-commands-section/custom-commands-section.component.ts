/**
 * CustomCommandsSectionComponent — Settings accordion section for slash commands.
 *
 * Port of CustomCommandsSection.tsx React component.
 * Features inline editor: add/edit/delete commands with name validation.
 * Injects CommandsStore and ApiService.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  Output,
  EventEmitter,
  OnInit,
  inject,
  signal,
  computed,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { CommandsStore } from '@shipagent/shared-state';
import type { CustomCommand, CommandUpdate } from '@shipagent/shared-types';

/** Command name validation: lowercase, numbers, hyphens only. */
const COMMAND_NAME_REGEX = /^[a-z][a-z0-9-]*$/;

@Component({
  selector: 'app-custom-commands-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="settings-section">
      <!-- Section header -->
      <button
        class="settings-section-header"
        (click)="toggled.emit()"
        [attr.aria-expanded]="isOpen"
      >
        <div class="flex items-center gap-2">
          <!-- Terminal icon -->
          <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4 17 10 11 4 5"></polyline>
            <line x1="12" y1="19" x2="20" y2="19"></line>
          </svg>
          <span class="font-medium text-foreground">Custom Commands</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-xs text-muted-foreground">
            {{ customCommands().length }} commands
          </span>
          <!-- Chevron -->
          <svg
            class="h-4 w-4 text-muted-foreground transition-transform"
            [class.rotate-180]="isOpen"
            viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"
          >
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </div>
      </button>

      @if (isOpen) {
        <div class="settings-section-content space-y-3">

          <!-- Command list -->
          @if (customCommands().length > 0) {
            <div class="max-h-64 overflow-y-auto space-y-2">
              @for (cmd of customCommands(); track cmd.id) {
                @if (expandedCommand() === cmd.id) {
                  <!-- Edit mode -->
                  <div class="p-3 rounded-lg border border-border bg-card space-y-3">
                    <div class="flex items-center gap-2">
                      <span class="text-muted-foreground">/</span>
                      <input
                        type="text"
                        [(ngModel)]="formName"
                        placeholder="command-name"
                        class="flex-1 h-8 font-mono px-3 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
                      />
                    </div>
                    <input
                      type="text"
                      [(ngModel)]="formDescription"
                      placeholder="Description (optional)"
                      class="w-full h-8 px-3 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
                    />
                    <textarea
                      [(ngModel)]="formBody"
                      placeholder="Command body - shipping instructions to expand..."
                      rows="3"
                      class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
                    ></textarea>
                    @if (formError()) {
                      <p class="text-xs text-destructive">{{ formError() }}</p>
                    }
                    <div class="flex justify-end gap-2">
                      <button
                        (click)="handleCancel()"
                        class="px-3 py-1.5 rounded-md border border-border text-muted-foreground text-xs hover:bg-muted transition-colors flex items-center gap-1"
                      >
                        <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                        Cancel
                      </button>
                      <button
                        (click)="handleSaveEdit(cmd)"
                        [disabled]="isLoading()"
                        class="px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs hover:bg-primary/90 disabled:opacity-50 transition-colors flex items-center gap-1"
                      >
                        <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                        Save
                      </button>
                    </div>
                  </div>
                } @else {
                  <!-- View mode -->
                  <div class="flex items-start justify-between p-2 rounded border border-border bg-card hover:bg-muted/30 transition-colors">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2">
                        <code class="text-xs font-mono text-domain-paperless">
                          /{{ cmd.name }}
                        </code>
                        @if (cmd.description) {
                          <span class="text-xs text-muted-foreground">— {{ cmd.description }}</span>
                        }
                      </div>
                      <p class="text-xs text-muted-foreground mt-1 truncate">
                        {{ cmd.body.slice(0, 60) }}{{ cmd.body.length > 60 ? '...' : '' }}
                      </p>
                    </div>
                    <div class="flex items-center gap-1 ml-2">
                      <button
                        (click)="handleStartEdit(cmd)"
                        class="p-1 rounded hover:bg-muted transition-colors text-muted-foreground"
                      >
                        <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                      </button>

                      @if (deleteConfirm() === cmd.id) {
                        <div class="flex items-center gap-1">
                          <button
                            (click)="handleDelete(cmd.id)"
                            [disabled]="isLoading()"
                            class="text-[10px] px-1.5 py-0.5 rounded bg-destructive/20 text-destructive hover:bg-destructive/30 disabled:opacity-50"
                          >
                            {{ isLoading() ? '...' : 'Confirm' }}
                          </button>
                          <button
                            (click)="deleteConfirm.set(null)"
                            class="p-1 rounded hover:bg-muted text-muted-foreground"
                          >
                            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                          </button>
                        </div>
                      } @else {
                        <button
                          (click)="deleteConfirm.set(cmd.id)"
                          class="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-destructive"
                        >
                          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>
                          </svg>
                        </button>
                      }
                    </div>
                  </div>
                }
              }
            </div>
          }

          <!-- Empty state -->
          @if (customCommands().length === 0 && !isCreating()) {
            <p class="text-xs text-muted-foreground text-center py-2">
              No custom commands yet. Create shortcuts for common shipping instructions.
            </p>
          }

          <!-- Create form -->
          @if (isCreating()) {
            <div class="p-3 rounded-lg border border-dashed border-primary bg-primary/5 space-y-3">
              <div class="flex items-center gap-2">
                <span class="text-muted-foreground">/</span>
                <input
                  type="text"
                  [(ngModel)]="formName"
                  placeholder="command-name"
                  class="flex-1 h-8 font-mono px-3 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
                />
              </div>
              <input
                type="text"
                [(ngModel)]="formDescription"
                placeholder="Description (optional)"
                class="w-full h-8 px-3 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
              />
              <textarea
                [(ngModel)]="formBody"
                placeholder="Command body - shipping instructions to expand..."
                rows="3"
                class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
              ></textarea>
              @if (formError()) {
                <p class="text-xs text-destructive">{{ formError() }}</p>
              }
              <div class="flex justify-end gap-2">
                <button
                  (click)="handleCancel()"
                  class="px-3 py-1.5 rounded-md border border-border text-muted-foreground text-xs hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  (click)="handleSaveNew()"
                  [disabled]="isLoading()"
                  class="px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs hover:bg-primary/90 disabled:opacity-50 transition-colors flex items-center gap-1"
                >
                  <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>
                  </svg>
                  Create
                </button>
              </div>
            </div>
          }

          <!-- Add button -->
          @if (!isCreating()) {
            <button
              (click)="handleStartCreate()"
              class="w-full flex items-center gap-2 px-3 py-2 rounded-md border border-dashed border-border hover:border-primary hover:bg-primary/5 transition-colors"
            >
              <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              <span class="text-sm text-muted-foreground">Create new command</span>
            </button>
          }
        </div>
      }
    </div>
  `,
})
export class CustomCommandsSectionComponent implements OnInit {
  private readonly apiService = inject(ApiService);
  private readonly commandsStore = inject(CommandsStore);

  @Input() isOpen = false;
  @Output() toggled = new EventEmitter<void>();

  customCommands = this.commandsStore.customCommands;

  expandedCommand = signal<string | null>(null);
  isCreating = signal(false);
  isLoading = signal(false);
  deleteConfirm = signal<string | null>(null);

  formName = '';
  formDescription = '';
  formBody = '';
  formError = signal<string | null>(null);

  private existingNames = computed(() =>
    new Set(this.customCommands().map((c) => c.name)),
  );

  ngOnInit(): void {
    this.loadCommands();
  }

  private async loadCommands(): Promise<void> {
    try {
      const result = await firstValueFrom(this.apiService.getCommands());
      this.commandsStore.setCommands(result.commands);
    } catch {
      /* non-critical */
    }
  }

  private validateName(name: string): string | null {
    if (!name) return 'Name is required';
    if (!COMMAND_NAME_REGEX.test(name)) {
      return 'Name must start with lowercase letter and contain only lowercase letters, numbers, and hyphens';
    }
    if (name.length > 50) return 'Name must be 50 characters or less';
    return null;
  }

  private resetForm(): void {
    this.formName = '';
    this.formDescription = '';
    this.formBody = '';
    this.formError.set(null);
  }

  handleStartCreate(): void {
    this.resetForm();
    this.isCreating.set(true);
    this.expandedCommand.set(null);
  }

  handleStartEdit(cmd: CustomCommand): void {
    this.formName = cmd.name;
    this.formDescription = cmd.description || '';
    this.formBody = cmd.body;
    this.formError.set(null);
    this.expandedCommand.set(cmd.id);
    this.isCreating.set(false);
  }

  handleCancel(): void {
    this.resetForm();
    this.expandedCommand.set(null);
    this.isCreating.set(false);
  }

  async handleSaveNew(): Promise<void> {
    const nameError = this.validateName(this.formName);
    if (nameError) {
      this.formError.set(nameError);
      return;
    }
    if (this.existingNames().has(this.formName)) {
      this.formError.set(`Command /${this.formName} already exists`);
      return;
    }
    if (!this.formBody.trim()) {
      this.formError.set('Command body is required');
      return;
    }
    this.isLoading.set(true);
    try {
      const created = await firstValueFrom(
        this.apiService.createCommand({
          name: this.formName,
          description: this.formDescription || undefined,
          body: this.formBody,
        }),
      );
      this.commandsStore.addCommand(created);
      this.resetForm();
      this.isCreating.set(false);
    } catch {
      this.formError.set('Failed to create command');
    } finally {
      this.isLoading.set(false);
    }
  }

  async handleSaveEdit(cmd: CustomCommand): Promise<void> {
    const nameError = this.validateName(this.formName);
    if (nameError) {
      this.formError.set(nameError);
      return;
    }
    if (this.formName !== cmd.name && this.existingNames().has(this.formName)) {
      this.formError.set(`Command /${this.formName} already exists`);
      return;
    }
    if (!this.formBody.trim()) {
      this.formError.set('Command body is required');
      return;
    }
    this.isLoading.set(true);
    try {
      const updatePayload: CommandUpdate = {};
      if (this.formName !== cmd.name) updatePayload.name = this.formName;
      if (this.formDescription !== (cmd.description || '')) {
        updatePayload.description = this.formDescription || undefined;
      }
      if (this.formBody !== cmd.body) updatePayload.body = this.formBody;

      const updated = await firstValueFrom(
        this.apiService.updateCommand(cmd.id, updatePayload),
      );
      this.commandsStore.updateCommand(cmd.id, updated);
      this.resetForm();
      this.expandedCommand.set(null);
    } catch {
      this.formError.set('Failed to update command');
    } finally {
      this.isLoading.set(false);
    }
  }

  async handleDelete(commandId: string): Promise<void> {
    this.isLoading.set(true);
    try {
      await firstValueFrom(this.apiService.deleteCommand(commandId));
      this.commandsStore.removeCommand(commandId);
      this.deleteConfirm.set(null);
    } catch {
      console.error('Failed to delete command');
    } finally {
      this.isLoading.set(false);
    }
  }
}
