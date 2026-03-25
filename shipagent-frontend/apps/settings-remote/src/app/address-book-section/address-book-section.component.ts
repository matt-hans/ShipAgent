/**
 * AddressBookSectionComponent — Settings accordion section with contact CRUD.
 *
 * Port of AddressBookSection.tsx React component.
 * Displays contacts list with search. Inline add/edit/delete without external modal.
 * Injects ContactsStore and ApiService.
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
import { ContactsStore } from '@shipagent/shared-state';
import { ContactFormComponent } from './contact-form.component';
import type { Contact, ContactCreate, ContactUpdate } from '@shipagent/shared-types';

@Component({
  selector: 'app-address-book-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, ContactFormComponent],
  template: `
    <div class="settings-section">
      <!-- Section header -->
      <button
        class="settings-section-header"
        (click)="onToggle.emit()"
        [attr.aria-expanded]="isOpen"
      >
        <div class="flex items-center gap-2">
          <!-- BookUser icon -->
          <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
            <circle cx="12" cy="10" r="2"></circle>
            <path d="M8 15c0-2.2 1.8-4 4-4s4 1.8 4 4"></path>
          </svg>
          <span class="font-medium text-foreground">Address Book</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-xs text-muted-foreground">
            {{ contacts().length }} contacts
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
          @if (showForm()) {
            <!-- Form view -->
            <div class="space-y-3">
              <button
                (click)="cancelForm()"
                class="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <!-- ArrowLeft icon -->
                <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="19" y1="12" x2="5" y2="12"></line>
                  <polyline points="12 19 5 12 12 5"></polyline>
                </svg>
                Back to contacts
              </button>
              <app-contact-form
                [contact]="editingContact()"
                [isLoading]="formLoading()"
                (submitted)="handleFormSubmit($event)"
                (cancelled)="cancelForm()"
              />
            </div>
          } @else {
            <!-- List view -->

            <!-- Search + Add -->
            <div class="flex gap-2">
              <div class="relative flex-1">
                <!-- Search icon -->
                <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="11" cy="11" r="8"></circle>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <input
                  type="text"
                  [(ngModel)]="searchQuery"
                  placeholder="Search contacts..."
                  class="w-full pl-8 pr-3 h-8 text-sm rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                />
              </div>
              <button
                (click)="startAdd()"
                class="h-8 px-2.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors flex items-center"
              >
                <!-- Plus icon -->
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              </button>
            </div>

            <!-- Tag filter chips -->
            @if (allTags().length > 0) {
              <div class="flex flex-wrap gap-1">
                <button
                  (click)="tagFilter.set(null)"
                  class="px-2 py-0.5 rounded text-[10px] transition-colors"
                  [class]="tagFilter() === null ? 'bg-primary text-primary-foreground' : 'bg-muted hover:bg-muted/80'"
                >
                  All
                </button>
                @for (tag of allTags(); track tag) {
                  <button
                    (click)="tagFilter.set(tag)"
                    class="px-2 py-0.5 rounded text-[10px] transition-colors"
                    [class]="tagFilter() === tag ? 'bg-primary text-primary-foreground' : 'bg-muted hover:bg-muted/80'"
                  >
                    {{ tag }}
                  </button>
                }
              </div>
            }

            <!-- Contact list -->
            @if (filteredContacts().length > 0) {
              <div class="max-h-80 overflow-y-auto space-y-2">
                @for (contact of filteredContacts(); track contact.id) {
                  <div class="flex items-start justify-between p-2 rounded border border-border bg-card hover:bg-muted/30 transition-colors">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2">
                        <code class="text-xs font-mono text-rose-400">
                          @{{ contact.handle }}
                        </code>
                        <span class="text-xs text-foreground truncate">
                          {{ contact.display_name }}
                        </span>
                      </div>
                      <p class="text-xs text-muted-foreground mt-0.5 truncate">
                        {{ formatLocation(contact) }}
                      </p>
                      @if (contact.tags && contact.tags.length > 0) {
                        <div class="flex flex-wrap gap-1 mt-1">
                          @for (tag of contact.tags.slice(0, 3); track tag) {
                            <span class="text-[9px] px-1.5 py-0 bg-muted rounded font-medium">
                              {{ tag }}
                            </span>
                          }
                        </div>
                      }
                    </div>
                    <div class="flex items-center gap-1 ml-2 flex-shrink-0">
                      <button
                        (click)="startEdit(contact)"
                        class="p-1 rounded hover:bg-muted transition-colors text-muted-foreground"
                      >
                        <!-- Edit icon -->
                        <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                      </button>

                      @if (deleteConfirm() === contact.id) {
                        <div class="flex items-center gap-1">
                          <button
                            (click)="handleDelete(contact.id)"
                            [disabled]="isDeleting()"
                            class="text-[10px] px-1.5 py-0.5 rounded bg-destructive/20 text-destructive hover:bg-destructive/30 disabled:opacity-50"
                          >
                            {{ isDeleting() ? '...' : 'Confirm' }}
                          </button>
                          <button
                            (click)="deleteConfirm.set(null)"
                            class="p-1 rounded hover:bg-muted text-muted-foreground"
                          >
                            <!-- X icon -->
                            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <line x1="18" y1="6" x2="6" y2="18"></line>
                              <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                          </button>
                        </div>
                      } @else {
                        <button
                          (click)="deleteConfirm.set(contact.id)"
                          class="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-destructive"
                        >
                          <!-- Trash icon -->
                          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>
                          </svg>
                        </button>
                      }
                    </div>
                  </div>
                }
              </div>
            } @else {
              <p class="text-xs text-muted-foreground text-center py-3">
                {{ searchQuery || tagFilter() ? 'No contacts match your filters.' : 'No contacts saved yet.' }}
              </p>
            }

            <!-- Footer count -->
            @if (contacts().length > 0) {
              <div class="text-[10px] font-mono uppercase tracking-wider text-muted-foreground text-center pt-1">
                @if (filteredContacts().length === contacts().length) {
                  {{ contacts().length }} saved contacts
                } @else {
                  {{ filteredContacts().length }} of {{ contacts().length }} matching
                }
              </div>
            }
          }
        </div>
      }
    </div>
  `,
})
export class AddressBookSectionComponent implements OnInit {
  private readonly apiService = inject(ApiService);
  private readonly contactsStore = inject(ContactsStore);

  @Input() isOpen = false;
  @Output() onToggle = new EventEmitter<void>();

  contacts = this.contactsStore.contacts;
  searchQuery = '';
  tagFilter = signal<string | null>(null);
  showForm = signal(false);
  editingContact = signal<Contact | null>(null);
  formLoading = signal(false);
  deleteConfirm = signal<string | null>(null);
  isDeleting = signal(false);

  allTags = computed(() => {
    const tagSet = new Set<string>();
    this.contacts().forEach((c) => c.tags?.forEach((t: string) => tagSet.add(t)));
    return Array.from(tagSet).sort();
  });

  filteredContacts = computed(() => {
    const q = this.searchQuery.toLowerCase();
    const tag = this.tagFilter();
    return this.contacts()
      .filter((c) => {
        if (q) {
          const matchesSearch =
            c.handle.toLowerCase().includes(q) ||
            c.display_name.toLowerCase().includes(q) ||
            c.city.toLowerCase().includes(q) ||
            (c.state_province?.toLowerCase().includes(q) ?? false);
          if (!matchesSearch) return false;
        }
        if (tag && !c.tags?.includes(tag)) return false;
        return true;
      })
      .sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
  });

  ngOnInit(): void {
    this.loadContacts();
  }

  private async loadContacts(): Promise<void> {
    try {
      const result = await firstValueFrom(this.apiService.getContacts());
      this.contactsStore.setContacts(result.contacts);
    } catch {
      /* non-critical */
    }
  }

  formatLocation(contact: Contact): string {
    const parts = [contact.city, contact.state_province].filter(Boolean);
    if (contact.country_code && contact.country_code !== 'US') {
      parts.push(contact.country_code);
    }
    return parts.join(', ');
  }

  startAdd(): void {
    this.editingContact.set(null);
    this.showForm.set(true);
  }

  startEdit(contact: Contact): void {
    this.editingContact.set(contact);
    this.showForm.set(true);
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.editingContact.set(null);
  }

  async handleFormSubmit(data: ContactCreate | ContactUpdate): Promise<void> {
    this.formLoading.set(true);
    try {
      const editing = this.editingContact();
      if (editing) {
        const updated = await firstValueFrom(
          this.apiService.updateContact(editing.id, data as ContactUpdate),
        );
        this.contactsStore.updateContact(editing.id, updated);
      } else {
        const created = await firstValueFrom(
          this.apiService.createContact(data as ContactCreate),
        );
        this.contactsStore.addContact(created);
      }
      this.showForm.set(false);
      this.editingContact.set(null);
    } catch (err) {
      console.error('Failed to save contact:', err);
    } finally {
      this.formLoading.set(false);
    }
  }

  async handleDelete(contactId: string): Promise<void> {
    this.isDeleting.set(true);
    try {
      await firstValueFrom(this.apiService.deleteContact(contactId));
      this.contactsStore.removeContact(contactId);
      this.deleteConfirm.set(null);
    } catch (err) {
      console.error('Failed to delete contact:', err);
    } finally {
      this.isDeleting.set(false);
    }
  }
}
