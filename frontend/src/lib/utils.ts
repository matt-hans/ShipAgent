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
