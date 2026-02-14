import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * Combines class names using clsx and merges Tailwind classes with tailwind-merge.
 * This allows conditional classes and proper Tailwind class deduplication.
 *
 * @example
 * cn("px-2", condition && "px-4") // Returns "px-4" if condition is true
 * cn("text-red-500 text-blue-500") // Returns "text-blue-500" (last wins)
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format an ISO date string as a human-readable relative time (e.g. "3h ago"). */
export function formatTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'Just now';
}
