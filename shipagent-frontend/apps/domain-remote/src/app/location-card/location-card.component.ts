/**
 * LocationCardComponent
 *
 * Port of React LocationCard.tsx.
 * Renders UPS location search results with expand/collapse panels.
 * Domain color: locator/teal via card-domain-locator CSS class.
 */

import {
  Component,
  Input,
  ChangeDetectionStrategy,
  signal,
} from '@angular/core';
import {
  MapPinIconComponent,
  ChevronDownIconComponent,
  PhoneIconComponent,
  HistoryIconComponent,
} from '@shipagent/shared-ui';
import type { LocationResult } from '@shipagent/shared-types';

interface DisplayItem {
  id: string;
  title: string;
  subtitle: string;
  address?: Record<string, string> | string;
  phone?: string;
  hours?: Record<string, string>;
  details?: Record<string, unknown>;
}

type DetailRow = [string, string];

function formatAddressLines(addr: Record<string, string>): string[] {
  return [
    addr['ConsigneeName'] || '',
    addr['AddressLine'] || addr['line'] || addr['address_line'] || '',
    [addr['City'] || addr['city'], addr['StateProvinceCode'] || addr['state']]
      .filter(Boolean)
      .join(', ') +
      (addr['PostalCode'] || addr['postal_code']
        ? ' ' + (addr['PostalCode'] || addr['postal_code'])
        : ''),
    (addr['CountryCode'] || addr['country_code'] || '') !== 'US'
      ? addr['CountryCode'] || addr['country_code'] || ''
      : '',
  ].filter(Boolean);
}

function formatAddressCompact(addr: Record<string, string>): string {
  return [
    addr['ConsigneeName'],
    addr['AddressLine'] || addr['line'] || addr['address_line'],
    [addr['City'] || addr['city'], addr['StateProvinceCode'] || addr['state']]
      .filter(Boolean)
      .join(', '),
    addr['PostalCode'] || addr['postal_code'],
  ]
    .filter(Boolean)
    .join(' · ');
}

function stringifyDetailValue(value: unknown): string {
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function flattenDetails(
  value: unknown,
  prefix: string,
  rows: DetailRow[],
): void {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      rows.push([prefix, '[]']);
      return;
    }
    value.forEach((item, index) => {
      flattenDetails(item, `${prefix}[${index}]`, rows);
    });
    return;
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const entries = Object.entries(record);
    if (entries.length === 0) {
      rows.push([prefix, '{}']);
      return;
    }
    entries.forEach(([key, item]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      flattenDetails(item, path, rows);
    });
    return;
  }
  rows.push([prefix, stringifyDetailValue(value)]);
}

function collectDetails(details?: Record<string, unknown>): DetailRow[] {
  if (!details) return [];
  const rows: DetailRow[] = [];
  flattenDetails(details, '', rows);
  return rows.filter(([key]) => key.trim().length > 0);
}

@Component({
  selector: 'app-location-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MapPinIconComponent,
    ChevronDownIconComponent,
    PhoneIconComponent,
    HistoryIconComponent,
  ],
  template: `
    <div class="card-premium p-4 space-y-3 border-l-4 card-domain-locator">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <sa-icon-map-pin class="w-4 h-4 text-[var(--color-domain-locator)]" />
          <h4 class="text-sm font-medium text-foreground">{{ title }}</h4>
        </div>
        <span class="badge badge-neutral">{{ items.length }} found</span>
      </div>

      <!-- Empty state -->
      @if (items.length === 0) {
        <p class="text-xs text-muted-foreground">No locations found for the given criteria.</p>
      }

      <!-- Locations / facilities list -->
      @if (items.length > 0) {
        <div class="rounded-md border border-border/50 overflow-hidden">
          @for (item of items; track item.id; let i = $index) {
            <div class="border-b border-border/30 last:border-0">
              <!-- Collapsed row -->
              <button
                (click)="toggleItem(i)"
                class="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50 transition-colors cursor-pointer"
              >
                <!-- Number badge -->
                <span class="w-6 h-6 rounded-full bg-[var(--color-domain-locator)]/15 text-[var(--color-domain-locator)] text-[10px] font-mono font-bold flex items-center justify-center flex-shrink-0">
                  {{ i + 1 }}
                </span>
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-foreground truncate">{{ item.title }}</p>
                  <p class="text-[11px] font-mono text-muted-foreground truncate">{{ item.subtitle }}</p>
                </div>
                @if (item.phone) {
                  <span class="text-[10px] font-mono text-muted-foreground hidden sm:block flex-shrink-0">
                    {{ item.phone }}
                  </span>
                }
                <sa-icon-chevron-down
                  class="w-3.5 h-3.5 text-muted-foreground transition-transform duration-200 flex-shrink-0"
                  [class.rotate-180]="expandedSet().has(i)"
                />
              </button>

              <!-- Expanded detail panel -->
              @if (expandedSet().has(i)) {
                <div class="animate-fade-in px-3 pb-3 pt-1 border-t border-border/30 ml-9">
                  <!-- Full address -->
                  @if (item.address) {
                    <div class="space-y-0.5 mb-2">
                      @if (isString(item.address)) {
                        <p class="text-xs text-foreground">{{ item.address }}</p>
                      } @else {
                        @for (line of getAddressLines(item.address); track $index) {
                          <p class="text-xs text-foreground">{{ line }}</p>
                        }
                      }
                    </div>
                  }

                  <!-- Phone link -->
                  @if (item.phone) {
                    <div class="flex items-center gap-1.5 mb-2">
                      <sa-icon-phone class="w-3 h-3 text-muted-foreground" />
                      <a
                        [href]="'tel:' + item.phone"
                        class="text-[10px] font-mono text-[var(--color-domain-locator)] hover:underline"
                      >
                        {{ item.phone }}
                      </a>
                    </div>
                  }

                  <!-- Operating hours -->
                  @if (item.hours && getHoursEntries(item.hours).length > 0) {
                    <div class="mt-2">
                      <div class="flex items-center gap-1.5 mb-1.5">
                        <sa-icon-history class="w-3 h-3 text-muted-foreground" />
                        <span class="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Hours</span>
                      </div>
                      <div class="grid grid-cols-2 gap-x-4 gap-y-0.5">
                        @for (entry of getHoursEntries(item.hours); track $index) {
                          <span class="text-[10px] font-mono text-muted-foreground">{{ entry[0] }}</span>
                          <span class="text-[10px] font-mono text-foreground">{{ entry[1] }}</span>
                        }
                      </div>
                    </div>
                  }

                  <!-- Full detail payload -->
                  @if (getDetailRows(item.details).length > 0) {
                    <div class="mt-2">
                      <div class="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
                        Full UPS Details
                      </div>
                      <div class="max-h-56 overflow-y-auto rounded border border-border/40 bg-background/40 p-2 space-y-1 scrollable">
                        @for (row of getDetailRows(item.details); track $index) {
                          <div class="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-2">
                            <span class="text-[10px] font-mono text-muted-foreground break-all">{{ row[0] }}</span>
                            <span class="text-[10px] font-mono text-foreground break-all">{{ row[1] }}</span>
                          </div>
                        }
                      </div>
                    </div>
                  }
                </div>
              }
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class LocationCardComponent {
  @Input({ required: true }) data!: LocationResult;

  readonly expandedSet = signal<Set<number>>(new Set());

  get isServiceCenters(): boolean {
    return this.data?.action === 'service_centers';
  }

  get title(): string {
    return this.isServiceCenters ? 'UPS Service Centers' : 'UPS Locations';
  }

  get items(): DisplayItem[] {
    if (!this.data) return [];
    if (this.isServiceCenters) {
      return (this.data.facilities ?? []).map((fac, index) => ({
        id: `facility-${index}-${fac.name || 'unknown'}`,
        title: fac.name || `Service Center ${index + 1}`,
        subtitle: (typeof fac.address === 'string' ? fac.address : '') || 'No address provided',
        address: typeof fac.address === 'string' ? fac.address : undefined,
        phone: fac.phone || fac.phones?.[0] || '',
        hours: fac.hours,
        details: fac.details,
      }));
    }
    return (this.data.locations ?? []).map((loc, index) => ({
      id: `location-${index}-${loc.id || 'unknown'}`,
      title: loc.address?.['ConsigneeName'] || `Location ${index + 1}`,
      subtitle: formatAddressCompact(loc.address) || `Location ID ${loc.id || 'N/A'}`,
      address: loc.address,
      phone: loc.phone || loc.phones?.[0] || '',
      hours: loc.hours,
      details: loc.details,
    }));
  }

  toggleItem(index: number): void {
    this.expandedSet.update((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  protected isString(value: unknown): value is string {
    return typeof value === 'string';
  }

  protected getAddressLines(addr: Record<string, string>): string[] {
    return formatAddressLines(addr);
  }

  protected getHoursEntries(hours?: Record<string, string>): [string, string][] {
    if (!hours) return [];
    return Object.entries(hours) as [string, string][];
  }

  protected getDetailRows(details?: Record<string, unknown>): DetailRow[] {
    return collectDetails(details);
  }
}
