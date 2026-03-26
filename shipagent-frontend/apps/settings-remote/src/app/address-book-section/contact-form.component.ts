/**
 * ContactFormComponent — Add/edit contact form with validation.
 *
 * Port of ContactForm.tsx React component.
 * Features:
 * - Handle auto-slug from display name
 * - Country dropdown with common codes
 * - Tag chips with add/remove
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  Output,
  EventEmitter,
  OnInit,
  signal,
  computed,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Contact, ContactCreate, ContactUpdate } from '@shipagent/shared-types';

const COUNTRY_CODES = [
  { code: 'US', name: 'United States' },
  { code: 'CA', name: 'Canada' },
  { code: 'MX', name: 'Mexico' },
  { code: 'GB', name: 'United Kingdom' },
  { code: 'DE', name: 'Germany' },
  { code: 'FR', name: 'France' },
  { code: 'AU', name: 'Australia' },
  { code: 'JP', name: 'Japan' },
];

@Component({
  selector: 'app-contact-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <form (ngSubmit)="handleSubmit()" class="space-y-4">

      <!-- Handle -->
      <div class="space-y-1.5">
        <label class="text-sm font-medium text-foreground">Handle</label>
        <div class="relative">
          <span class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground font-mono text-sm pointer-events-none">@</span>
          <input
            type="text"
            [(ngModel)]="handle"
            name="handle"
            placeholder="auto-generated if empty"
            class="w-full font-mono pl-7 px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
            (input)="onHandleInput($event)"
          />
        </div>
      </div>

      <!-- Display Name -->
      <div class="space-y-1.5">
        <label class="text-sm font-medium text-foreground">Display Name *</label>
        <input
          type="text"
          [(ngModel)]="displayName"
          name="displayName"
          placeholder="John Doe"
          required
          class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          (input)="onDisplayNameInput($event)"
        />
      </div>

      <!-- Company + Attention -->
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">Company</label>
          <input
            type="text"
            [(ngModel)]="company"
            name="company"
            placeholder="Acme Inc"
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">Attention</label>
          <input
            type="text"
            [(ngModel)]="attentionName"
            name="attentionName"
            placeholder="Shipping Dept"
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
      </div>

      <!-- Phone + Email -->
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">Phone</label>
          <input
            type="tel"
            [(ngModel)]="phone"
            name="phone"
            placeholder="+14155550100"
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">Email</label>
          <input
            type="email"
            [(ngModel)]="email"
            name="email"
            placeholder="john@example.com"
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
      </div>

      <!-- Address Line 1 -->
      <div class="space-y-1.5">
        <label class="text-sm font-medium text-foreground">Address Line 1 *</label>
        <input
          type="text"
          [(ngModel)]="addressLine1"
          name="addressLine1"
          placeholder="123 Main St"
          required
          class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
      </div>

      <!-- Address Line 2 -->
      <div class="space-y-1.5">
        <label class="text-sm font-medium text-foreground">Address Line 2</label>
        <input
          type="text"
          [(ngModel)]="addressLine2"
          name="addressLine2"
          placeholder="Suite 100"
          class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
      </div>

      <!-- City + State -->
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">City *</label>
          <input
            type="text"
            [(ngModel)]="city"
            name="city"
            placeholder="San Francisco"
            required
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">State/Province</label>
          <input
            type="text"
            [(ngModel)]="stateProvince"
            name="stateProvince"
            placeholder="CA"
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
      </div>

      <!-- Postal + Country -->
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">Postal Code *</label>
          <input
            type="text"
            [(ngModel)]="postalCode"
            name="postalCode"
            placeholder="94105"
            required
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground">Country</label>
          <select
            [(ngModel)]="countryCode"
            name="countryCode"
            class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          >
            @for (c of countries; track c.code) {
              <option [value]="c.code">{{ c.code }} — {{ c.name }}</option>
            }
          </select>
        </div>
      </div>

      <!-- Tags -->
      <div class="space-y-2">
        <label class="text-sm font-medium text-foreground">Tags</label>
        <div class="flex flex-wrap gap-1.5">
          @for (tag of tags(); track tag) {
            <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-muted rounded text-xs">
              {{ tag }}
              <button
                type="button"
                (click)="removeTag(tag)"
                class="hover:text-destructive"
              >
                <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </span>
          }
        </div>
        <div class="flex gap-2">
          <input
            type="text"
            [(ngModel)]="tagInput"
            name="tagInput"
            placeholder="Add tag"
            class="flex-1 h-8 px-3 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
            (keydown.enter)="addTagOnEnter($event)"
          />
          <button
            type="button"
            (click)="addTag()"
            class="h-8 px-2.5 rounded-md border border-border text-muted-foreground hover:bg-muted transition-colors"
          >
            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
        </div>
      </div>

      <!-- Notes -->
      <div class="space-y-1.5">
        <label class="text-sm font-medium text-foreground">Notes</label>
        <textarea
          [(ngModel)]="notes"
          name="notes"
          placeholder="Additional notes..."
          rows="2"
          class="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
        ></textarea>
      </div>

      <!-- Actions -->
      <div class="flex justify-end gap-2 pt-2">
        <button
          type="button"
          (click)="cancelled.emit()"
          class="px-4 py-2 rounded-md border border-border text-muted-foreground hover:bg-muted text-sm transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          [disabled]="!isValid() || isLoading"
          class="px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {{ isLoading ? 'Saving...' : (contact ? 'Update Contact' : 'Create Contact') }}
        </button>
      </div>
    </form>
  `,
})
export class ContactFormComponent implements OnInit {
  @Input() contact: Contact | null = null;
  @Input() isLoading = false;
  @Output() submitted = new EventEmitter<ContactCreate | ContactUpdate>();
  @Output() cancelled = new EventEmitter<void>();

  readonly countries = COUNTRY_CODES;

  // Form fields
  displayName = '';
  handle = '';
  private handleManuallyEdited = false;
  company = '';
  attentionName = '';
  phone = '';
  email = '';
  addressLine1 = '';
  addressLine2 = '';
  city = '';
  stateProvince = '';
  postalCode = '';
  countryCode = 'US';
  notes = '';

  tags = signal<string[]>([]);
  tagInput = '';

  isValid = computed(() => {
    return !!(this.displayName && this.addressLine1 && this.city && this.postalCode);
  });

  ngOnInit(): void {
    if (this.contact) {
      this.displayName = this.contact.display_name || '';
      this.handle = this.contact.handle || '';
      this.handleManuallyEdited = !!this.contact.handle;
      this.company = this.contact.company || '';
      this.attentionName = this.contact.attention_name || '';
      this.phone = this.contact.phone || '';
      this.email = this.contact.email || '';
      this.addressLine1 = this.contact.address_line_1 || '';
      this.addressLine2 = this.contact.address_line_2 || '';
      this.city = this.contact.city || '';
      this.stateProvince = this.contact.state_province || '';
      this.postalCode = this.contact.postal_code || '';
      this.countryCode = this.contact.country_code || 'US';
      this.notes = this.contact.notes || '';
      this.tags.set(this.contact.tags || []);
    }
  }

  onDisplayNameInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.displayName = value;
    if (!this.contact && !this.handleManuallyEdited) {
      this.handle = this.autoSlug(value);
    }
  }

  onHandleInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.handle = value.toLowerCase().replace(/[^a-z0-9-]/g, '');
    this.handleManuallyEdited = true;
  }

  private autoSlug(name: string): string {
    return name
      .toLowerCase()
      .replace(/'/g, '')
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 50);
  }

  addTagOnEnter(event: Event): void {
    event.preventDefault();
    this.addTag();
  }

  addTag(): void {
    const trimmed = this.tagInput.trim().toLowerCase();
    if (trimmed && !this.tags().includes(trimmed)) {
      this.tags.update((tags) => [...tags, trimmed]);
      this.tagInput = '';
    }
  }

  removeTag(tag: string): void {
    this.tags.update((tags) => tags.filter((t) => t !== tag));
  }

  handleSubmit(): void {
    if (!this.isValid()) return;

    const data: ContactCreate | ContactUpdate = {
      display_name: this.displayName,
      handle: this.handle || undefined,
      company: this.company || undefined,
      attention_name: this.attentionName || undefined,
      phone: this.phone || undefined,
      email: this.email || undefined,
      address_line_1: this.addressLine1,
      address_line_2: this.addressLine2 || undefined,
      city: this.city,
      state_province: this.stateProvince || undefined,
      postal_code: this.postalCode,
      country_code: this.countryCode,
      tags: this.tags().length > 0 ? this.tags() : undefined,
      notes: this.notes || undefined,
    };

    this.submitted.emit(data);
  }
}
