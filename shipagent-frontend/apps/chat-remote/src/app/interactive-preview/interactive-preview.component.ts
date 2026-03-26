/**
 * InteractivePreviewComponent — Interactive (single shipment) preview card.
 *
 * Shows full address details (ship-from / ship-to grid), service with
 * available alternatives, package info, accessorials, estimated cost,
 * and an expandable commercial invoice section for international shipments.
 *
 * Matches React's InteractivePreviewCard component from PreviewCard.tsx.
 *
 * UX enhancement: clicking a field value in the detail view pre-populates
 * the refine input with a suggestion like "Change [field] to ".
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  ViewChild,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormatCurrencyPipe,
  ChevronDownIconComponent,
  PackageIconComponent,
  MapPinIconComponent,
  UserIconComponent,
  FileTextIconComponent,
} from '@shipagent/shared-ui';
import { PreviewActionsComponent } from '../preview-actions/preview-actions.component';
import type { BatchPreview, AvailableServiceOption } from '@shipagent/shared-types';

/* ────────────────── Accessorial Extraction ────────────────── */

/** Simplified-format boolean flag keys mapped to human-readable labels. */
const SIMPLIFIED_ACCESSORIALS: [string, string][] = [
  ['saturdayDelivery', 'Saturday Delivery'],
  ['holdForPickup', 'Hold for Pickup'],
  ['liftGatePickup', 'Lift Gate Pickup'],
  ['liftGateDelivery', 'Lift Gate Delivery'],
  ['directDeliveryOnly', 'Direct Delivery Only'],
  ['deliverToAddresseeOnly', 'Addressee Only'],
  ['carbonNeutral', 'Carbon Neutral'],
  ['dropoffAtFacility', 'Drop-off at Facility'],
  ['insideDelivery', 'Inside Delivery'],
  ['shipperRelease', 'Shipper Release'],
];

/**
 * Extract human-readable accessorial labels from the resolved payload.
 * Mirrors the React extractAccessorials function.
 */
function extractAccessorials(payload: Record<string, unknown>): string[] {
  const labels: string[] = [];
  try {
    for (const [key, label] of SIMPLIFIED_ACCESSORIALS) {
      if (payload[key]) labels.push(label);
    }
    const dc = payload['deliveryConfirmation'];
    if (dc === '1' || dc === 1) labels.push('Signature Required');
    else if (dc === '2' || dc === 2) labels.push('Adult Signature Required');
    if (payload['notificationEmail']) labels.push('Email Notification');
    const packages = payload['packages'] as Record<string, unknown>[] | undefined;
    if (Array.isArray(packages)) {
      for (const pkg of packages) {
        if (pkg['largePackage'] && !labels.includes('Large Package')) labels.push('Large Package');
        if (pkg['additionalHandling'] && !labels.includes('Additional Handling')) labels.push('Additional Handling');
        if (pkg['declaredValue'] && !labels.some(l => l.startsWith('Declared Value'))) {
          labels.push(`Declared Value: $${pkg['declaredValue']}`);
        }
      }
    }
  } catch {
    // Gracefully return whatever we have
  }
  return labels;
}

/* ────────────────── Invoice Data Extraction ────────────────── */

interface InvoiceProduct {
  description: string;
  commodityCode?: string;
  originCountry?: string;
  quantity?: string;
  unitValue?: string;
  lineTotal?: string;
}

interface InvoiceData {
  formType: string;
  invoiceNumber?: string;
  invoiceDate?: string;
  reasonForExport?: string;
  currencyCode?: string;
  products: InvoiceProduct[];
  invoiceTotal?: string;
  invoiceTotalCurrency?: string;
  freightCharges?: string;
  insuranceCharges?: string;
  termsOfShipment?: string;
  purchaseOrderNumber?: string;
  comments?: string;
  shipperName?: string;
  recipientName?: string;
}

/**
 * Extract invoice data from the resolved payload for international shipments.
 * Mirrors the React extractInvoiceData function.
 */
function extractInvoiceData(payload: Record<string, unknown>): InvoiceData | null {
  try {
    const forms = payload['internationalForms'] as Record<string, unknown> | undefined;
    if (!forms) return null;

    const rawProducts = forms['Product'] as Record<string, unknown>[] | Record<string, unknown> | undefined;
    const productList = Array.isArray(rawProducts) ? rawProducts : rawProducts ? [rawProducts] : [];

    const products: InvoiceProduct[] = productList.map((p) => {
      const unit = p['Unit'] as Record<string, unknown> | undefined;
      const rawValue = unit?.['Value'];
      const valueStr = typeof rawValue === 'string' ? rawValue
        : typeof rawValue === 'object' && rawValue ? (rawValue as Record<string, unknown>)['MonetaryValue'] as string
        : undefined;
      const qtyStr = (unit?.['Number'] as string) || undefined;
      return {
        description: (p['Description'] as string) || '',
        commodityCode: (p['CommodityCode'] as string) || undefined,
        originCountry: (p['OriginCountryCode'] as string) || undefined,
        quantity: qtyStr,
        unitValue: valueStr || undefined,
        lineTotal: valueStr && qtyStr
          ? (parseFloat(valueStr) * parseFloat(qtyStr)).toFixed(2)
          : undefined,
      };
    });

    const invoiceLineTotal = payload['invoiceLineTotal'] as Record<string, unknown> | undefined;
    const shipper = payload['shipper'] as Record<string, unknown> | undefined;
    const shipTo = payload['shipTo'] as Record<string, unknown> | undefined;

    const freightRaw = forms['FreightCharges'];
    const freightVal = typeof freightRaw === 'string' ? freightRaw
      : (freightRaw as Record<string, unknown> | undefined)?.['MonetaryValue'] as string | undefined;

    const insuranceRaw = forms['InsuranceCharges'];
    const insuranceVal = typeof insuranceRaw === 'string' ? insuranceRaw
      : (insuranceRaw as Record<string, unknown> | undefined)?.['MonetaryValue'] as string | undefined;

    return {
      formType: (forms['FormType'] as string) || '01',
      invoiceNumber: forms['InvoiceNumber'] as string | undefined,
      invoiceDate: forms['InvoiceDate'] as string | undefined,
      reasonForExport: forms['ReasonForExport'] as string | undefined,
      currencyCode: forms['CurrencyCode'] as string | undefined,
      products,
      invoiceTotal: (invoiceLineTotal?.['monetaryValue'] as string) || undefined,
      invoiceTotalCurrency: (invoiceLineTotal?.['currencyCode'] as string) || undefined,
      freightCharges: freightVal,
      insuranceCharges: insuranceVal,
      termsOfShipment: forms['TermsOfShipment'] as string | undefined,
      purchaseOrderNumber: forms['PurchaseOrderNumber'] as string | undefined,
      comments: forms['Comments'] as string | undefined,
      shipperName: (shipper?.['name'] as string) || (shipper?.['Name'] as string) || undefined,
      recipientName: (shipTo?.['name'] as string) || (shipTo?.['Name'] as string) || undefined,
    };
  } catch {
    return null;
  }
}

@Component({
  selector: 'app-interactive-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormatCurrencyPipe,
    ChevronDownIconComponent,
    PackageIconComponent,
    MapPinIconComponent,
    UserIconComponent,
    FileTextIconComponent,
    PreviewActionsComponent,
  ],
  styles: [`
    .chevron-rotated {
      transform: rotate(180deg);
    }
    .field-clickable {
      cursor: pointer;
      border-radius: 4px;
      transition: background-color 150ms ease;
    }
    .field-clickable:hover {
      background-color: oklch(0.25 0.015 240 / 0.5);
    }
    .invoice-enter {
      animation: invoiceFadeIn 200ms ease-out;
    }
    @keyframes invoiceFadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  `],
  template: `
    <div class="card-premium overflow-hidden max-w-lg">
      <!-- Header -->
      <div class="px-4 pt-4 pb-3 border-b border-border/30">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5">
            <sa-icon-package class="w-4 h-4 text-blue-400" />
            <h3 class="text-sm font-semibold text-slate-200">Shipment Preview</h3>
          </div>
          <span class="badge badge-info text-[10px]">Ready</span>
        </div>
      </div>

      <div class="px-4 py-3 space-y-3">
        <!-- Ship From / Ship To Grid -->
        <div class="grid grid-cols-2 gap-2">
          <!-- From -->
          <div class="bg-slate-800/50 rounded-lg px-2.5 py-2">
            <div class="flex items-center gap-1 mb-0.5">
              <sa-icon-map-pin class="w-3 h-3 text-slate-500" />
              <span class="text-[10px] font-medium text-slate-500 uppercase tracking-wider">From</span>
            </div>
            @if (preview.shipper) {
              <div class="text-xs text-slate-200 leading-snug">
                <p class="font-medium truncate">{{ preview.shipper.name }}</p>
                <p class="text-slate-400 truncate">
                  {{ preview.shipper.addressLine1 }}{{ preview.shipper.addressLine2 ? ', ' + preview.shipper.addressLine2 : '' }}
                </p>
                <p class="text-slate-400">
                  {{ preview.shipper.city }}, {{ preview.shipper.stateProvinceCode }} {{ preview.shipper.postalCode }}
                </p>
              </div>
            } @else {
              <p class="text-xs text-slate-400">From config</p>
            }
          </div>

          <!-- To -->
          <div class="bg-slate-800/50 rounded-lg px-2.5 py-2">
            <div class="flex items-center gap-1 mb-0.5">
              <sa-icon-user class="w-3 h-3 text-slate-500" />
              <span class="text-[10px] font-medium text-slate-500 uppercase tracking-wider">To</span>
              @if (preview.ship_to?.country && preview.ship_to?.country !== 'US') {
                <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[8px] font-mono font-medium uppercase">
                  {{ preview.ship_to?.country }}
                </span>
              }
            </div>
            @if (preview.ship_to) {
              <div class="text-xs text-slate-200 leading-snug">
                <p class="font-medium truncate field-clickable px-1 -mx-1" tabindex="0" role="button" (click)="suggestRefine('recipient name', preview.ship_to!.name)" (keydown.enter)="suggestRefine('recipient name', preview.ship_to!.name)">
                  {{ preview.ship_to.name }}
                </p>
                @if (preview.ship_to.attention_name) {
                  <p class="text-slate-400">Attn: {{ preview.ship_to.attention_name }}</p>
                }
                <p class="text-slate-400 truncate field-clickable px-1 -mx-1" tabindex="0" role="button" (click)="suggestRefine('address', preview.ship_to!.address1)" (keydown.enter)="suggestRefine('address', preview.ship_to!.address1)">
                  {{ preview.ship_to.address1 }}{{ preview.ship_to.address2 ? ', ' + preview.ship_to.address2 : '' }}
                </p>
                <p class="text-slate-400 field-clickable px-1 -mx-1" tabindex="0" role="button" (click)="suggestRefine('city/state/zip', preview.ship_to!.city + ', ' + preview.ship_to!.state + ' ' + preview.ship_to!.postal_code)" (keydown.enter)="suggestRefine('city/state/zip', preview.ship_to!.city + ', ' + preview.ship_to!.state + ' ' + preview.ship_to!.postal_code)">
                  {{ preview.ship_to.city }}, {{ preview.ship_to.state }} {{ preview.ship_to.postal_code }}
                </p>
                @if (preview.ship_to.phone) {
                  <p class="text-slate-400 text-[10px] font-mono field-clickable px-1 -mx-1" tabindex="0" role="button" (click)="suggestRefine('phone', preview.ship_to!.phone!)" (keydown.enter)="suggestRefine('phone', preview.ship_to!.phone!)">
                    {{ preview.ship_to.phone }}
                  </p>
                }
              </div>
            } @else {
              <p class="text-xs text-slate-400">--</p>
            }
          </div>
        </div>

        <!-- Service / Weight / Account bar -->
        <div class="flex items-center justify-between bg-slate-800/50 rounded-lg px-3 py-1.5 text-xs">
          <div class="flex items-center gap-1">
            <span class="text-slate-500">Service:</span>
            <span class="font-medium text-white field-clickable px-1 -mx-1" tabindex="0" role="button" (click)="suggestRefine('service', displayedServiceName)" (keydown.enter)="suggestRefine('service', displayedServiceName)">
              {{ displayedServiceName }}
            </span>
          </div>
          <div class="flex items-center gap-1">
            <span class="text-slate-500">Wt:</span>
            <span class="font-medium text-white field-clickable px-1 -mx-1" tabindex="0" role="button" (click)="suggestRefine('weight', (preview.weight_lbs ?? 1) + ' lbs')" (keydown.enter)="suggestRefine('weight', (preview.weight_lbs ?? 1) + ' lbs')">
              {{ preview.weight_lbs ?? 1.0 }} lbs
            </span>
          </div>
          <div class="flex items-center gap-1">
            <span class="text-slate-500">Acct:</span>
            <span class="font-medium text-white font-mono">{{ preview.account_number || '****' }}</span>
          </div>
        </div>

        <!-- Accessorials -->
        @if (accessorials.length > 0) {
          <div class="flex flex-wrap gap-1.5">
            @for (label of accessorials; track label) {
              <span class="px-2 py-0.5 rounded-full bg-slate-700/60 border border-slate-600/40 text-[10px] text-slate-300">
                {{ label }}
              </span>
            }
          </div>
        }

        <!-- Available services from UPS Shop -->
        @if (availableServices.length > 0) {
          <div class="rounded-lg border border-slate-700/60 bg-slate-900/40 p-2">
            <p class="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">
              Available Services
            </p>
            <div class="space-y-0.5 max-h-24 overflow-y-auto pr-1">
              @for (svc of availableServices; track svc.code) {
                <button
                  type="button"
                  class="w-full rounded-md border px-2 py-1 text-left transition-colors cursor-pointer"
                  [class.border-primary/40]="svc.code === effectiveServiceCode"
                  [class.bg-primary/10]="svc.code === effectiveServiceCode"
                  [class.border-slate-700/70]="svc.code !== effectiveServiceCode"
                  [class.bg-slate-800/40]="svc.code !== effectiveServiceCode"
                  [class.hover:bg-slate-800/60]="svc.code !== effectiveServiceCode"
                  (click)="selectService(svc.code)"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-xs text-slate-200">{{ svc.name }} ({{ svc.code }})</span>
                    <span class="text-xs font-mono"
                      [class.text-primary]="svc.code === effectiveServiceCode"
                      [class.text-slate-300]="svc.code !== effectiveServiceCode"
                    >
                      {{ svc.estimated_cost_cents | formatCurrency }}
                    </span>
                  </div>
                  @if (svc.delivery_days) {
                    <p class="text-[10px] text-slate-500 mt-0.5">
                      Est. transit: {{ svc.delivery_days }} day{{ svc.delivery_days === '1' ? '' : 's' }}
                    </p>
                  }
                </button>
              }
            </div>
            @if (preview.service_selection_notice) {
              <p class="mt-2 text-[10px] text-slate-400">{{ preview.service_selection_notice }}</p>
            }
          </div>
        }

        <!-- Estimated Cost -->
        <div class="bg-gradient-to-r from-emerald-500/10 to-emerald-500/5 border border-emerald-500/20 rounded-lg px-3 py-1.5 flex items-center justify-between">
          <p class="text-[10px] font-medium text-emerald-400 uppercase tracking-wider">Estimated Cost</p>
          <p class="text-lg font-bold text-emerald-400">
            {{ displayedTotalCostCents | formatCurrency }}
          </p>
        </div>

        <!-- View Invoice link (international only) -->
        @if (isInternational && invoiceData) {
          <div class="flex justify-center">
            <button
              type="button"
              class="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
              (click)="showInvoice.set(!showInvoice())"
            >
              <sa-icon-file-text class="w-3.5 h-3.5" />
              <span>{{ showInvoice() ? 'Hide Invoice' : 'View Invoice' }}</span>
            </button>
          </div>
        }

        <!-- Inline Commercial Invoice (expandable) -->
        @if (showInvoice() && invoiceData) {
          <div class="invoice-enter rounded-lg border border-slate-700/50 bg-slate-900/60 p-3 space-y-3">
            <div>
              <h4 class="text-sm font-semibold text-white">Commercial Invoice</h4>
              <div class="flex items-center gap-3 mt-1 text-[10px] font-mono text-slate-400">
                @if (invoiceData.invoiceNumber) {
                  <span>#{{ invoiceData.invoiceNumber }}</span>
                }
                @if (invoiceData.invoiceDate) {
                  <span>{{ invoiceData.invoiceDate }}</span>
                }
              </div>
            </div>

            <!-- Parties -->
            @if (invoiceData.shipperName || invoiceData.recipientName) {
              <div class="grid grid-cols-2 gap-3">
                @if (invoiceData.shipperName) {
                  <div>
                    <p class="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-0.5">Shipper</p>
                    <p class="text-xs text-slate-200">{{ invoiceData.shipperName }}</p>
                  </div>
                }
                @if (invoiceData.recipientName) {
                  <div>
                    <p class="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-0.5">Recipient</p>
                    <p class="text-xs text-slate-200">{{ invoiceData.recipientName }}</p>
                  </div>
                }
              </div>
            }

            <!-- Commodities table -->
            @if (invoiceData.products.length > 0) {
              <div>
                <p class="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5">Commodities</p>
                <div class="border border-slate-700/50 rounded-lg overflow-hidden">
                  <table class="w-full text-xs">
                    <thead>
                      <tr class="bg-slate-800/60 text-[10px] text-slate-400 uppercase tracking-wider">
                        <th class="text-left px-2.5 py-1.5 font-medium">Description</th>
                        <th class="text-left px-2 py-1.5 font-medium">HS Code</th>
                        <th class="text-center px-2 py-1.5 font-medium">Qty</th>
                        <th class="text-right px-2.5 py-1.5 font-medium">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (p of invoiceData.products; track $index) {
                        <tr class="border-t border-slate-800/40">
                          <td class="px-2.5 py-1.5 text-slate-200">
                            <div>{{ p.description }}</div>
                            @if (p.originCountry) {
                              <span class="text-[9px] text-slate-500">Origin: {{ p.originCountry }}</span>
                            }
                          </td>
                          <td class="px-2 py-1.5 font-mono text-slate-400 text-[10px]">
                            {{ p.commodityCode || '—' }}
                          </td>
                          <td class="px-2 py-1.5 text-center text-slate-300">
                            {{ p.quantity || '—' }}
                          </td>
                          <td class="px-2.5 py-1.5 text-right font-mono text-slate-300">
                            @if (p.lineTotal) {
                              {{ '$' + p.lineTotal }}
                            } @else if (p.unitValue) {
                              {{ '$' + p.unitValue }}
                            } @else {
                              —
                            }
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              </div>
            }

            <!-- Summary -->
            <div class="bg-slate-800/40 rounded-lg p-3 space-y-1.5">
              @if (invoiceData.invoiceTotal) {
                <div class="flex justify-between text-xs">
                  <span class="text-slate-400">Invoice Total</span>
                  <span class="font-mono text-white font-medium">
                    {{ '$' + invoiceData.invoiceTotal }}
                    @if (invoiceData.invoiceTotalCurrency) {
                      <span class="text-slate-400 ml-1">{{ invoiceData.invoiceTotalCurrency }}</span>
                    }
                  </span>
                </div>
              }
              @if (invoiceData.freightCharges) {
                <div class="flex justify-between text-xs">
                  <span class="text-slate-400">Freight</span>
                  <span class="font-mono text-slate-300">{{ '$' + invoiceData.freightCharges }}</span>
                </div>
              }
              @if (invoiceData.termsOfShipment) {
                <div class="flex justify-between text-xs">
                  <span class="text-slate-400">Terms</span>
                  <span class="text-slate-300">{{ invoiceData.termsOfShipment }}</span>
                </div>
              }
              @if (invoiceData.reasonForExport) {
                <div class="flex justify-between text-xs">
                  <span class="text-slate-400">Reason</span>
                  <span class="text-slate-300">{{ invoiceData.reasonForExport }}</span>
                </div>
              }
            </div>
          </div>
        }

        <!-- Warnings -->
        @if (hasWarnings) {
          <div class="bg-amber-500/10 border border-amber-500/20 rounded-lg p-2">
            <p class="text-sm text-amber-300 font-medium mb-1">Rating Warning</p>
            @for (row of preview.preview_rows; track row.row_number) {
              @for (w of row.warnings; track $index) {
                <p class="text-xs text-amber-200/80">{{ w }}</p>
              }
            }
          </div>
        }

        <!-- Expandable Full Payload -->
        @if (preview.resolved_payload) {
          <div>
            <button
              type="button"
              class="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
              (click)="showPayload.set(!showPayload())"
            >
              <sa-icon-chevron-down
                class="w-3.5 h-3.5 transition-transform"
                [class.chevron-rotated]="showPayload()"
              />
              <span>Full Payload</span>
            </button>
            @if (showPayload()) {
              <pre class="mt-2 bg-slate-900/80 border border-slate-700/50 rounded-lg p-3 text-xs text-slate-300 overflow-x-auto max-h-64 overflow-y-auto font-mono">{{ payloadJson }}</pre>
            }
          </div>
        }
      </div>

      <!-- Actions (hidden for historical previews) -->
      @if (readOnly) {
        <div class="px-4 py-2 border-t border-border/20 flex items-center justify-center">
          <span class="badge badge-success text-[10px] font-medium">Completed</span>
        </div>
      } @else {
        <app-preview-actions
          [isConfirming]="isConfirming"
          (confirm)="handleConfirmWithService()"
          (cancel)="cancel.emit()"
          (refine)="refine.emit($event)"
        />
      }
    </div>
  `,
})
export class InteractivePreviewComponent {
  @Input({ required: true }) preview!: BatchPreview;
  @Input() isConfirming = false;
  /** When true, hide action buttons and show a read-only status badge (historical preview). */
  @Input() readOnly = false;

  @Output() confirm = new EventEmitter<{ selectedServiceCode?: string }>();
  @Output() cancel = new EventEmitter<void>();
  @Output() refine = new EventEmitter<string>();

  @ViewChild(PreviewActionsComponent) private previewActions?: PreviewActionsComponent;

  /** Whether the full payload JSON is expanded. */
  readonly showPayload = signal(false);

  /** Whether the commercial invoice section is expanded. */
  readonly showInvoice = signal(false);

  /** Computed: displayed service name — reflects user selection. */
  get displayedServiceName(): string {
    const code = this.effectiveServiceCode;
    if (code) {
      const svc = this.availableServices.find(s => s.code === code);
      if (svc) return svc.name;
    }
    return this.preview.service_name || this.preview.service_code || 'UPS Ground';
  }

  /** User-selected service code (overrides preview default). */
  readonly selectedServiceCode = signal<string | null>(null);

  /** Computed: effective service code — user selection overrides preview default. */
  get effectiveServiceCode(): string | null {
    return this.selectedServiceCode() || this.preview.service_code || null;
  }

  /** Select a different service level — updates cost display immediately. */
  selectService(code: string): void {
    this.selectedServiceCode.set(code);
  }

  /** Emit confirm with the selected service code for the execution. */
  handleConfirmWithService(): void {
    const code = this.effectiveServiceCode;
    this.confirm.emit({ selectedServiceCode: code || undefined });
  }

  /** Computed: available services list. */
  get availableServices(): AvailableServiceOption[] {
    return this.preview.available_services || [];
  }

  /** Computed: displayed total cost in cents. */
  get displayedTotalCostCents(): number {
    const selected = this.availableServices.find(s => s.code === this.effectiveServiceCode);
    return selected?.estimated_cost_cents ?? this.preview.total_estimated_cost_cents;
  }

  /** Computed: whether the destination is international. */
  get isInternational(): boolean {
    return !!(this.preview.ship_to?.country && this.preview.ship_to.country !== 'US');
  }

  /** Computed: whether any row has warnings. */
  get hasWarnings(): boolean {
    return this.preview.preview_rows?.some(r => r.warnings?.length > 0) ?? false;
  }

  /** Computed: accessorial labels extracted from resolved_payload. */
  get accessorials(): string[] {
    return this.preview.resolved_payload ? extractAccessorials(this.preview.resolved_payload) : [];
  }

  /** Computed: invoice data extracted from resolved_payload for international shipments. */
  get invoiceData(): InvoiceData | null {
    return this.preview.resolved_payload ? extractInvoiceData(this.preview.resolved_payload) : null;
  }

  /** Computed: pretty-printed payload JSON for the expandable section. */
  get payloadJson(): string {
    return this.preview.resolved_payload ? JSON.stringify(this.preview.resolved_payload, null, 2) : '';
  }

  /**
   * Pre-populate the refine input with a suggestion for the clicked field.
   *
   * This is a UX enhancement beyond the React implementation. Clicking a
   * field value opens the refine input with a partially filled suggestion
   * so the user can type the new value directly.
   */
  suggestRefine(fieldName: string, _currentValue: string): void {
    if (this.previewActions) {
      this.previewActions.openWithSuggestion(`Change the ${fieldName} to `);
    }
  }
}
