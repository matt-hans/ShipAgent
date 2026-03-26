/**
 * ContactCardComponent
 *
 * Port of React ContactCard.tsx.
 * Renders a saved contact with @handle, name, address, and action buttons.
 * Uses contacts domain color via card-domain-contacts CSS class.
 * Supports three states: active, confirmed, deleted.
 */

import {
  Component,
  Input,
  ChangeDetectionStrategy,
  signal,
  inject,
} from '@angular/core';
import {
  UserIconComponent,
  CheckIconComponent,
  TrashIconComponent,
} from '@shipagent/shared-ui';
import { ApiService } from '@shipagent/shared-api';
import type { ContactSavedResult } from '@shipagent/shared-types';
import { firstValueFrom } from 'rxjs';

type CardState = 'active' | 'confirmed' | 'deleted';

@Component({
  selector: 'app-contact-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    UserIconComponent,
    CheckIconComponent,
    TrashIconComponent,
  ],
  template: `
    <!-- Confirmed state — minimal collapsed card -->
    @if (cardState() === 'confirmed') {
      <div class="card-premium p-3 border-l-4 card-domain-contacts">
        <div class="flex items-center gap-2 text-xs">
          <sa-icon-check class="w-3.5 h-3.5 text-success" />
          <span class="text-muted-foreground">
            Contact <code class="font-mono text-[var(--color-domain-contacts)]">@{{ data.handle }}</code> saved
          </span>
        </div>
      </div>
    }

    <!-- Deleted state -->
    @if (cardState() === 'deleted') {
      <div class="card-premium p-3 border-l-4 border-border">
        <div class="flex items-center gap-2 text-xs">
          <sa-icon-trash class="w-3.5 h-3.5 text-muted-foreground" />
          <span class="text-muted-foreground">
            Contact <code class="font-mono">@{{ data.handle }}</code> removed
          </span>
        </div>
      </div>
    }

    <!-- Active state -->
    @if (cardState() === 'active') {
      <div class="card-premium p-4 space-y-3 border-l-4 card-domain-contacts">
        <!-- Header -->
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <sa-icon-user class="w-4 h-4 text-[var(--color-domain-contacts)]" />
            <h4 class="text-sm font-medium text-foreground">Contact Saved</h4>
          </div>
          <span class="badge {{ data.action === 'created' ? 'badge-success' : 'badge-info' }}">
            {{ data.action === 'created' ? 'CREATED' : 'UPDATED' }}
          </span>
        </div>

        <!-- Contact details -->
        <div class="space-y-2">
          <!-- Name and handle -->
          <div class="flex items-center gap-2">
            <span class="text-sm font-semibold text-foreground">{{ data.display_name }}</span>
            <code class="text-xs font-mono text-[var(--color-domain-contacts)]">@{{ data.handle }}</code>
          </div>

          <!-- Company / Attention -->
          @if (data.company || data.attention_name) {
            <div class="text-xs text-muted-foreground">
              @if (data.company) {
                <span>{{ data.company }}</span>
              }
              @if (data.company && data.attention_name) {
                <span> · </span>
              }
              @if (data.attention_name) {
                <span>Attn: {{ data.attention_name }}</span>
              }
            </div>
          }

          <!-- Address -->
          <div class="text-xs text-muted-foreground leading-relaxed">
            <p>{{ data.address_line_1 }}</p>
            @if (data.address_line_2) {
              <p>{{ data.address_line_2 }}</p>
            }
            <p>
              {{ data.city }}{{ data.state_province ? ', ' + data.state_province : '' }} {{ data.postal_code }}
              {{ data.country_code !== 'US' ? ' ' + data.country_code : '' }}
            </p>
          </div>

          <!-- Phone / Email -->
          @if (data.phone || data.email) {
            <div class="flex items-center gap-3 text-xs text-muted-foreground">
              @if (data.phone) {
                <span>{{ data.phone }}</span>
              }
              @if (data.email) {
                <span>{{ data.email }}</span>
              }
            </div>
          }

          <!-- Tags -->
          @if (data.tags && data.tags.length > 0) {
            <div class="flex flex-wrap gap-1.5">
              @for (tag of data.tags; track tag) {
                <span class="text-[10px] px-2 py-0.5 bg-muted rounded font-medium">{{ tag }}</span>
              }
            </div>
          }
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-2 pt-1 border-t border-border">
          <button
            (click)="handleConfirm()"
            class="btn-primary px-3 py-1.5 text-xs gap-1.5"
          >
            <sa-icon-check class="w-3.5 h-3.5" />
            Confirm
          </button>

          <!-- Delete confirmation -->
          @if (deleteConfirm()) {
            <div class="flex items-center gap-1.5 ml-auto">
              <span class="text-[10px] text-muted-foreground">Delete?</span>
              <button
                (click)="handleDelete()"
                [disabled]="isDeleting()"
                class="px-2 py-1 text-[10px] rounded bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
              >
                {{ isDeleting() ? 'Deleting...' : 'Yes' }}
              </button>
              <button
                (click)="deleteConfirm.set(false)"
                class="px-2 py-1 text-[10px] rounded bg-muted hover:bg-muted/80"
              >
                No
              </button>
            </div>
          } @else {
            <button
              (click)="deleteConfirm.set(true)"
              class="btn-secondary px-3 py-1.5 text-xs gap-1.5 ml-auto"
            >
              <sa-icon-trash class="w-3.5 h-3.5" />
              Delete
            </button>
          }
        </div>
      </div>
    }
  `,
})
export class ContactCardComponent {
  @Input({ required: true }) data!: ContactSavedResult;

  private readonly apiService = inject(ApiService);

  readonly cardState = signal<CardState>('active');
  readonly isDeleting = signal(false);
  readonly deleteConfirm = signal(false);

  async handleConfirm(): Promise<void> {
    this.cardState.set('confirmed');
  }

  async handleDelete(): Promise<void> {
    this.isDeleting.set(true);
    try {
      // Search for the contact by handle to get the ID
      const response = await firstValueFrom(this.apiService.getContacts());
      const contact = response.contacts.find((c) => c.handle === this.data.handle);
      if (contact) {
        await firstValueFrom(this.apiService.deleteContact(contact.id));
      }
      this.cardState.set('deleted');
    } catch (error) {
      console.error('Failed to delete contact:', error);
    } finally {
      this.isDeleting.set(false);
      this.deleteConfirm.set(false);
    }
  }
}
