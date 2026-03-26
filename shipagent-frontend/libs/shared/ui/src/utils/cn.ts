/**
 * cn() — Class name utility.
 *
 * Combines class names using clsx (conditional logic) and merges
 * conflicting Tailwind classes using tailwind-merge.
 *
 * Port of the React frontend's `cn()` from `frontend/src/lib/utils.ts`.
 *
 * @example
 * cn("px-2 py-1", condition && "px-4") // "px-4 py-1" when condition is true
 * cn("text-red-500", "text-blue-500")  // "text-blue-500" (last wins)
 */

import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
