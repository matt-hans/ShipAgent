/**
 * FormatCurrencyPipe — Transforms an amount in cents to a USD currency string.
 *
 * Port of `formatCurrency()` from `frontend/src/lib/utils.ts`.
 *
 * @example
 * {{ 1299 | formatCurrency }}  // "$12.99"
 * {{ 0 | formatCurrency }}     // "$0.00"
 */

import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'formatCurrency',
  standalone: true,
  pure: true,
})
export class FormatCurrencyPipe implements PipeTransform {
  /**
   * Transform a cent amount to a USD currency string.
   * @param cents The amount in cents (integer).
   * @returns Formatted USD string, e.g. "$12.99".
   */
  transform(cents: number | null | undefined): string {
    if (cents == null) return '$0.00';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(cents / 100);
  }
}
