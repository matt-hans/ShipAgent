/**
 * Brand icon components — Platform logos and brand-specific glyphs.
 *
 * Port of `frontend/src/components/ui/brand-icons.tsx`.
 * Each brand icon is a standalone Angular component with OnPush change detection.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  ViewEncapsulation,
} from '@angular/core';
import { NgClass } from '@angular/common';

/**
 * ShopifyIconComponent — Shopify platform brand icon.
 */
@Component({
  selector: 'sa-brand-shopify',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none">
    <text
      x="12"
      y="17"
      text-anchor="middle"
      font-family="system-ui, -apple-system, sans-serif"
      font-size="18"
      font-weight="700"
      fill="currentColor"
    >S</text>
  </svg>`,
})
export class ShopifyIconComponent {
  @Input() class = '';
}

/**
 * AmazonIconComponent — Amazon platform brand icon.
 */
@Component({
  selector: 'sa-brand-amazon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none">
    <text
      x="12"
      y="17"
      text-anchor="middle"
      font-family="system-ui, -apple-system, sans-serif"
      font-size="18"
      font-weight="700"
      fill="currentColor"
    >A</text>
  </svg>`,
})
export class AmazonIconComponent {
  @Input() class = '';
}

/**
 * WooCommerceIconComponent — WooCommerce platform brand icon.
 */
@Component({
  selector: 'sa-brand-woocommerce',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none">
    <text
      x="12"
      y="17"
      text-anchor="middle"
      font-family="system-ui, -apple-system, sans-serif"
      font-size="18"
      font-weight="700"
      fill="currentColor"
    >W</text>
  </svg>`,
})
export class WooCommerceIconComponent {
  @Input() class = '';
}

/**
 * SAPIconComponent — SAP platform brand icon.
 */
@Component({
  selector: 'sa-brand-sap',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none">
    <text
      x="12"
      y="17"
      text-anchor="middle"
      font-family="system-ui, -apple-system, sans-serif"
      font-size="14"
      font-weight="700"
      fill="currentColor"
    >SAP</text>
  </svg>`,
})
export class SAPIconComponent {
  @Input() class = '';
}

/**
 * OracleIconComponent — Oracle platform brand icon.
 */
@Component({
  selector: 'sa-brand-oracle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none">
    <text
      x="12"
      y="17"
      text-anchor="middle"
      font-family="system-ui, -apple-system, sans-serif"
      font-size="11"
      font-weight="700"
      fill="currentColor"
    >ORA</text>
  </svg>`,
})
export class OracleIconComponent {
  @Input() class = '';
}

/**
 * DataSourceIconComponent — Generic data source icon with optional connected indicator.
 * Port of DataSourceIcon with `connected` prop.
 */
@Component({
  selector: 'sa-brand-datasource',
  standalone: true,
  imports: [NgClass],
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <div class="relative inline-flex">
      <svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <ellipse cx="12" cy="6" rx="8" ry="3" />
        <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
        <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
      </svg>
      @if (connected) {
        <span class="absolute -top-0.5 -right-0.5 w-2 h-2 bg-success rounded-full"></span>
      }
    </div>
  `,
})
export class DataSourceIconComponent {
  @Input() class = '';
  /** Show a green connected indicator dot when true. */
  @Input() connected = false;
}

export const ALL_BRAND_ICON_COMPONENTS = [
  ShopifyIconComponent,
  AmazonIconComponent,
  WooCommerceIconComponent,
  SAPIconComponent,
  OracleIconComponent,
  DataSourceIconComponent,
] as const;
