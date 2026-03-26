/**
 * TimeAgoPipe — Transforms an ISO date string to a relative time string.
 *
 * Port of `formatTimeAgo()` from `frontend/src/lib/utils.ts`.
 * Unlike RelativeTimePipe, this also handles days.
 *
 * @example
 * {{ "2026-01-01T00:00:00Z" | timeAgo }}  // "3d ago", "2h ago", "5m ago", "Just now"
 */

import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'timeAgo',
  standalone: true,
  pure: true,
})
export class TimeAgoPipe implements PipeTransform {
  /**
   * Transform an ISO date string to a relative time string.
   * @param dateStr ISO 8601 date string or Date object.
   * @returns Relative time string like "3d ago", "2h ago", "5m ago", or "Just now".
   */
  transform(dateStr: string | Date | null | undefined): string {
    if (!dateStr) return 'Just now';
    const diff = Date.now() - new Date(dateStr).getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return 'Just now';
  }
}
