/**
 * RelativeTimePipe — Transforms a Date to a relative time string.
 *
 * Port of `formatRelativeTime()` from `frontend/src/lib/utils.ts`.
 *
 * @example
 * {{ someDate | relativeTime }}  // "5m ago", "2h ago", "Just now"
 */

import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'relativeTime',
  standalone: true,
  pure: true,
})
export class RelativeTimePipe implements PipeTransform {
  /**
   * Transform a Date to a relative time string.
   * @param date The date to format.
   * @returns Relative time string like "5m ago", "2h ago", or "Just now".
   */
  transform(date: Date | string | null | undefined): string {
    if (!date) return 'Just now';
    const dateObj = typeof date === 'string' ? new Date(date) : date;
    const diff = Date.now() - dateObj.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);

    if (hours > 0) return `${hours}h ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return 'Just now';
  }
}
